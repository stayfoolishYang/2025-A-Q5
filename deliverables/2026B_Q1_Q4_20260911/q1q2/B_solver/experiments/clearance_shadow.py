"""Offline clearance shadow measurements; never used to select an online action.

The hooks cover Q3 next_view, Q4 Hypotheses.next and depth-one diagnostic v1.
Every planner must run only once; the hook captures its generated candidates and
returned real scores. Scores absent outside a diagnostic beam stay null.
"""
import argparse
from contextlib import contextmanager
import copy
import csv
import gzip
import hashlib
import inspect
import json
from pathlib import Path
import pickle
import random
import sys
import time

import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from geometry import (ERROR_DEG, diameter, intersect_disk, mec,
                      nearest_certified_clear_point, wedge)
from particles import feasible, signal_counts

SAFE_RADIUS = 19.999
GAP_TOLERANCE_M = 1e-8


def fingerprint(value):
    return hashlib.sha256(pickle.dumps(value, protocol=5)).hexdigest()


def rng_snapshot(solver=None):
    hypotheses = {}
    if solver is not None:
        for channel, track in solver.tracks.items():
            hyp = track.get('hyp')
            if hyp is not None:
                hypotheses[channel] = copy.deepcopy(hyp.rng.bit_generator.state)
    return fingerprint((random.getstate(), np.random.get_state(), hypotheses))


def _ranks(values, descending=False):
    available = [(i, value) for i, value in enumerate(values) if value is not None and np.isfinite(value)]
    available.sort(key=lambda item: (-item[1] if descending else item[1], item[0]))
    result, previous, rank = [None]*len(values), None, 0
    for ordinal, (index, value) in enumerate(available, 1):
        if previous is None or value != previous:
            rank = ordinal
        result[index], previous = rank, value
    return result


def _unique(values, tolerance=0.):
    ordered = sorted(v for v in values if v is not None and np.isfinite(v))
    representatives = []
    for value in ordered:
        if not representatives or abs(value-representatives[-1]) > tolerance:
            representatives.append(value)
    return len(representatives)


def _posterior_metrics(post, point):
    if not len(post) or not np.isfinite(post).all():
        return dict(valid=False, D=None, R=None, G=None, certified=False,
                    certified_completion_cost=None, completion_reason='empty_or_nonfinite_posterior')
    d = diameter(post)[0]
    center, radius = mec(post)
    result = dict(valid=True, D=float(d), R=float(radius), G=max(0., float(radius)-SAFE_RADIUS),
                  posterior_vertices=np.asarray(post).tolist(),
                  certified=False, certified_completion_cost=None,
                  completion_reason='MEC_exceeds_safe_radius')
    if radius <= SAFE_RADIUS:
        try:
            landing, metadata = nearest_certified_clear_point(post, point, SAFE_RADIUS, center, radius)
            result.update(certified=True, certified_completion_cost=float(np.linalg.norm(landing-point)/5+5),
                          certified_point=landing.tolist(), completion_reason=None,
                          completion_selector=metadata.get('mode'))
        except (ValueError, RuntimeError, ArithmeticError) as exc:
            result['completion_reason'] = f'certificate_not_numerically_verified:{type(exc).__name__}'
    return result


def compute_state_metrics(poly, particles, current, candidates, *, planner_kind,
                          candidate_current_scores=None, score_direction='min', chosen_index=None,
                          move_times=None, candidate_estimated_completion_costs=None,
                          candidate_proxy_scores=None, metadata=None, max_scenarios=8,
                          gap_lambda=0.2):
    """Pure read-only metrics on an ALREADY generated candidate array.

    Fixed witnesses are chosen once per state, before candidate evaluation:
    evenly spaced live-hypothesis indices crossed with three fixed angular
    errors. Every scenario has weight 1/(M*3), including repeated observations;
    weights are never assigned by the number of observation bins. They are
    design weights, not calibrated probabilities. Q3 may instead use fixed
    polygon/centroid geometric witnesses with omni radius 1000 m, explicitly
    labelled as a witness design. Empty Q4 hypotheses yield null cert scores.

    A possible no-signal outcome absent from the fixed witness sample is added
    with ZERO weight for the sampled-worst metrics only. It cannot alter the
    fixed-weight certificate score. All posterior geometry is hypothetical.
    """
    if max_scenarios < 1 or score_direction not in ('min', 'max'):
        raise ValueError('positive scenario count and min/max score direction required')
    poly = np.asarray(poly, dtype=float).copy()
    particles = np.asarray(particles if particles is not None else np.empty((0,5)), dtype=float).copy()
    current = np.asarray(current, dtype=float).copy()
    points = np.asarray(candidates, dtype=float).copy().reshape(-1,2)
    if not len(poly) or not np.isfinite(poly).all() or not np.isfinite(points).all():
        raise ValueError('finite nonempty polygon and finite original candidates required')
    times = np.asarray(move_times if move_times is not None else np.linalg.norm(points-current,axis=1)/5+5, dtype=float)
    if times.shape != (len(points),) or not np.isfinite(times).all():
        raise ValueError('one finite move time per original candidate required')
    current_scores = candidate_current_scores or {}
    estimated = candidate_estimated_completion_costs or {}
    proxy = candidate_proxy_scores or {}
    witness_basis = 'fixed_live_hypothesis_indices'
    if len(particles):
        indices = np.linspace(0,len(particles)-1,min(max_scenarios,len(particles))).astype(int)
        witnesses = particles[indices]
    elif planner_kind.startswith('q3'):
        positions = np.vstack((poly, poly.mean(axis=0)))
        indices = np.linspace(0,len(positions)-1,min(max_scenarios,len(positions))).astype(int)
        witnesses = np.c_[positions[indices], np.zeros(len(indices)), np.full(len(indices),1000.), np.zeros(len(indices))]
        witness_basis = 'fixed_polygon_centroid_witnesses_omni_radius1000_not_a_probability_model'
    else:
        indices, witnesses = np.array([],dtype=int), np.empty((0,5))
        witness_basis = 'no_live_hypotheses_certificate_score_unavailable'
    errors = (-ERROR_DEG,0.,ERROR_DEG)
    weight = 1./(len(witnesses)*len(errors)) if len(witnesses) else 0.
    current_d = float(diameter(poly)[0])
    current_r = float(mec(poly)[1])
    current_gap = max(0.,current_r-SAFE_RADIUS)
    records = []
    for index, point in enumerate(points):
        if len(particles):
            no_possible = bool(feasible(particles,(point,'no_signal',None)).any())
        elif planner_kind.startswith('q3'):
            no_possible = bool(np.max(np.linalg.norm(poly-point,axis=1)) > 1000.)
        else:
            no_possible = True
        outcomes, repeated_posteriors = [], {}
        for witness_id, witness in enumerate(witnesses):
            no_signal = bool(feasible(witness.reshape(1,5),(point,'no_signal',None))[0])
            distance = float(np.linalg.norm(witness[:2]-point))
            for error_id, error in enumerate(errors):
                if no_signal:
                    kind, post = 'no_signal', poly.copy()
                elif distance <= 5:
                    kind, post = 'near', intersect_disk(poly,point,5.)
                else:
                    kind = 'direction'
                    angle = float(np.rad2deg(np.arctan2(*(witness[:2]-point)[::-1]))+error)
                    post = intersect_disk(wedge(poly,point,angle),point,1500.)
                if kind in ('near','no_signal'):
                    if kind not in repeated_posteriors:
                        repeated_posteriors[kind] = _posterior_metrics(post,point)
                    metrics = repeated_posteriors[kind]
                else:
                    metrics = _posterior_metrics(post,point)
                outcomes.append(dict(scenario_id=f'{witness_id}:{error_id}', hypothesis_index=int(indices[witness_id]),
                                     angle_error_deg=error, weight=weight, outcome=kind,
                                     no_signal_keeps_hard_polygon=kind=='no_signal' and np.array_equal(post,poly),
                                     **metrics))
        if no_possible and not any(outcome['outcome']=='no_signal' for outcome in outcomes):
            outcomes.append(dict(scenario_id='conservative_no_signal_witness',hypothesis_index=None,
                                 angle_error_deg=None,weight=0.,outcome='no_signal',
                                 no_signal_keeps_hard_polygon=True, **_posterior_metrics(poly,point)))
        valid = [outcome for outcome in outcomes if outcome['valid']]
        worst = {key:max((outcome[key] for outcome in valid),default=None) for key in ('D','R','G')}
        cert_score = sum(outcome['weight'] for outcome in outcomes if outcome['valid'] and outcome['certified']) if len(witnesses) else None
        completion_known = bool(outcomes) and all(outcome['valid'] and outcome['certified'] for outcome in outcomes)
        available = index in current_scores
        diagnostic = planner_kind == 'diagnostic_v1'
        records.append(dict(candidate_index=index,point=point.tolist(),move_time_s=float(times[index]),
            current_planner_score=float(current_scores[index]) if available else None,
            current_score_reason=None if available else 'not_evaluated_by_original_planner',
            current_v1_score=float(current_scores[index]) if diagnostic and available else None,
            current_v1_score_reason=(None if diagnostic and available else 'outside_original_v1_beam' if diagnostic else 'not_a_diagnostic_v1_call'),
            proxy_score=float(proxy[index]) if index in proxy else None,
            proxy_score_provenance='deterministic_reconstruction_verified_against_original_beam' if index in proxy else None,
            estimated_completion_cost=float(estimated[index]) if index in estimated else None,
            estimated_completion_reason=None if index in estimated else 'not_returned_by_original_estimator_for_this_candidate',
            estimated_completion_provenance='original_v1_total_score_minus_original_move_time' if diagnostic and index in estimated else None,
            D_worst=worst['D'],R_worst=worst['R'],G_worst=worst['G'],
            sampled_cert_score=cert_score,sampled_cert_score_reason=None if len(witnesses) else 'no_live_hypothesis_scenarios',
            sampled_weight_sum=sum(outcome['weight'] for outcome in outcomes),
            certified_completion_cost=max(outcome['certified_completion_cost'] for outcome in outcomes) if completion_known else None,
            certified_completion_reason=None if completion_known else 'not_all_sampled_outcomes_have_a_verified_certified_region',
            certified_completion_aggregation='sampled_worst_completion_after_measurement_excludes_measurement_cost',
            no_signal_possible=no_possible,no_signal_keeps_hard_polygon=bool(no_possible),
            invalid_posterior_count=sum(not outcome['valid'] for outcome in outcomes),
            outcomes=outcomes))
    for rank_name, field, descending in (
            ('rank_current','current_planner_score',score_direction=='max'),
            ('rank_D','D_worst',False),('rank_R','R_worst',False),('rank_G','G_worst',False),
            ('rank_completion','certified_completion_cost',False),
            ('rank_estimated_completion','estimated_completion_cost',False)):
        for record, rank in zip(records,_ranks([r[field] for r in records],descending)):
            record[rank_name] = rank
    gaps = [record['G_worst'] for record in records]
    all_known = bool(gaps) and all(value is not None for value in gaps)
    gap_choice = int(np.argmin([value+gap_lambda*t for value,t in zip(gaps,times)])) if all_known else None
    min_time_choice = int(np.argmin(times)) if len(times) else None
    score_scope = 'actual_original_beam_only' if planner_kind=='diagnostic_v1' else 'supplied_original_active_scores'
    return dict(planner_kind=planner_kind,metadata=metadata or {},original_candidates=points.tolist(),
        planner_selected_index=chosen_index,planner_selected_point=points[chosen_index].tolist() if chosen_index is not None else None,
        selected_point_provenance='original_planner_result_before_execution_overrides',
        current_D=current_d,current_R=current_r,current_G=current_gap,
        scenario_design=dict(basis=witness_basis,hypothesis_indices=indices.tolist(),
            fixed_hypotheses=witnesses.tolist(),input_particle_count=len(particles),
            input_particles_sha256=hashlib.sha256(particles.tobytes()).hexdigest(),
            error_degrees=list(errors),scenario_weight=weight,scenario_count=len(witnesses)*len(errors),
            common_across_candidates=True,calibrated_probability=False,
            worst_only_extra_no_signal_weight=0.),
        input_polygon=poly.tolist(),dog_position=current.tolist(),
        shadow_branch_scope='fixed_shared_witness_posteriors; differs from original planner representative/outcome aggregation',
        candidate_count=len(records),candidate_records=records,current_score_scope=score_scope,
        current_score_count=len(current_scores),current_score_unique_values=_unique(list(current_scores.values())),
        no_signal_candidate_count=sum(r['no_signal_possible'] for r in records),
        G_equals_current_count=sum(g is not None and abs(g-current_gap)<=GAP_TOLERANCE_M for g in gaps),
        G_unique_values=_unique(gaps,GAP_TOLERANCE_M),gap_equality_tolerance_m=GAP_TOLERANCE_M,
        GAP_DEGENERATE_STATE=all_known and _unique(gaps,GAP_TOLERANCE_M)==1,
        shadow_G_rule_lambda=gap_lambda,shadow_G_rule_lambda_units='m/s',shadow_G_rule_choice=gap_choice,
        min_move_time_choice=min_time_choice,G_rule_matches_min_move_time=gap_choice==min_time_choice if gap_choice is not None else None,
        G_rule_differs_from_planner=gap_choice!=chosen_index if gap_choice is not None and chosen_index is not None else None,
        policy_use='shadow_only_never_used_for_action_selection')


class ShadowCollector:
    def __init__(self, solver=None, max_states=4, max_scenarios=8):
        self.solver, self.max_states, self.max_scenarios = solver,max_states,max_scenarios
        self.states, self.skipped = [], []

    def capture(self, poly, particles, current, candidates, **kwargs):
        """Extension hook: pass captured active scores, never call policy twice."""
        if self.max_states is not None and len(self.states)>=self.max_states:
            self.skipped.append(dict(planner_kind=kwargs['planner_kind'],reason='predeclared_state_cap'))
            return None
        before = fingerprint((poly,particles,current,candidates,kwargs))
        rng_before = rng_snapshot(self.solver)
        state = compute_state_metrics(poly,particles,current,candidates,max_scenarios=self.max_scenarios,**kwargs)
        if before != fingerprint((poly,particles,current,candidates,kwargs)) or rng_before != rng_snapshot(self.solver):
            raise AssertionError('Shadow computation changed its inputs or policy RNG state')
        state['shadow_state_index'] = len(self.states)
        state['rng_and_inputs_unchanged'] = True
        state['rng_scope'] = 'Python/NumPy global and live policy Hypotheses generators; geometry MEC uses its own existing fixed seed'
        if self.solver is not None:
            state['action_index_before_selection'] = self.solver.api.index
            state['virtual_time_before_selection'] = self.solver.api.virtual_time
        self.states.append(state)
        return state

    def finalize(self, actions):
        for state in self.states:
            index = state.get('action_index_before_selection')
            action = actions[index] if index is not None and index<len(actions) else None
            state['next_executed_action'] = copy.deepcopy(action)
            state['executed_point'] = action.get('position') if action else None
            state['planner_point_equals_executed_point'] = state['planner_selected_point']==state['executed_point'] if action else None
            if state['planner_kind'] in ('q3_active','q4_active'):
                state['execution_override_detected'] = bool(action and action.get('path')=='/measure'
                    and state['planner_selected_point']!=action.get('position'))
                state['execution_override_reason'] = ('original_repeat_view_25_25_guard'
                    if state.get('metadata',{}).get('repeat_view_guard_would_override') else
                    'other_downstream_change') if state['execution_override_detected'] else None
            if self.solver is not None and state['planner_kind']=='diagnostic_v1':
                meta = state['metadata']
                decisions = self.solver.trace.get(meta['target_channel'],{}).get('diagnostic_decisions',[])
                decision = decisions[meta['decision_index']] if meta['decision_index']<len(decisions) else None
                state['original_plan_accepted'] = decision.get('accepted') if decision else None
                state['original_grid_cost'] = decision.get('grid_cost') if decision else None
                state['executed_planned_measurement'] = bool(decision and decision.get('accepted') and action
                    and action.get('path')=='/measure' and action.get('channel')==meta['target_channel']
                    and action.get('position')==state['planner_selected_point'])


@contextmanager
def diagnostic_hook(collector):
    """Temporary process-local capture; original choose executes exactly once."""
    import directional.diagnostic_recovery as recovery
    original, original_candidates = recovery.choose, recovery.candidates
    signature = inspect.signature(original)
    def wrapped(*args,**kwargs):
        bound = signature.bind(*args,**kwargs)
        bound.apply_defaults()
        values = bound.arguments
        depth = values['depth'] if values['depth'] is not None else values['config'].get('depth',1)
        if depth != 1:
            collector.skipped.append(dict(planner_kind='diagnostic_v1',reason='depth_not_one'))
            return original(*args,**kwargs)
        captured = []
        def capture_candidates(*a,**kw):
            points = original_candidates(*a,**kw)
            captured.append(points.copy())
            return points
        recovery.candidates = capture_candidates
        try:
            plan = original(*args,**kwargs)
        finally:
            recovery.candidates = original_candidates
        if plan is None:
            return plan
        if len(captured)!=1:
            raise AssertionError('Original depth-one planner did not generate candidates exactly once')
        points = captured[0]
        poly,particles,current = values['poly'],values['particles'],values['current']
        move = np.linalg.norm(points-current,axis=1)/5+5+int(values['channel']!=values['target_channel'])
        counts = signal_counts(particles,points,'cpu') if len(particles) else np.zeros(len(points))
        probability = counts/len(particles) if len(particles) else np.full(len(points),0.5)
        _,a,b = diameter(poly)
        va,vb = a-points,b-points
        angular = abs(va[:,0]*vb[:,1]-va[:,1]*vb[:,0])/np.maximum(np.linalg.norm(va,axis=1)*np.linalg.norm(vb,axis=1),1e-9)
        split = values['config'].get('split_weight',0.5)
        proxy = (split*np.minimum(probability,1-probability)+(1-split)*probability*angular)/move
        scores,completion = {},{}
        for record in plan['candidate_scores']:
            matches = np.flatnonzero(np.all(points==np.asarray(record['point']),axis=1))
            if len(matches)!=1:
                raise AssertionError('Original beam point not uniquely present in captured candidates')
            index = int(matches[0])
            if float(proxy[index]) != record['proxy_score']:
                raise AssertionError('Reconstructed proxy differs from original beam proxy')
            scores[index],completion[index] = record['estimated_cost'],record['estimated_cost']-record['move_time']
        chosen = int(np.flatnonzero(np.all(points==np.asarray(plan['point']),axis=1))[0])
        plan_before = fingerprint(plan)
        channel = values['target_channel']
        decision_index = len(collector.solver.trace.get(channel,{}).get('diagnostic_decisions',[])) if collector.solver else 0
        collector.capture(poly,particles,current,points,planner_kind='diagnostic_v1',
            candidate_current_scores=scores,score_direction='min',chosen_index=chosen,move_times=move,
            candidate_estimated_completion_costs=completion,
            candidate_proxy_scores={i:float(value) for i,value in enumerate(proxy)},
            metadata=dict(target_channel=channel,decision_index=decision_index,depth=1,
                          beam_width=values['config'].get('beam_width',4),original_candidate_generation_calls=1))
        if fingerprint(plan)!=plan_before:
            raise AssertionError('Shadow changed the original plan')
        return plan
    recovery.choose = wrapped
    try:
        yield collector
    finally:
        recovery.choose, recovery.candidates = original, original_candidates


def _target_channel(collector,poly=None,hyp=None):
    if collector.solver is None:
        return None
    for channel,track in collector.solver.tracks.items():
        if (hyp is not None and track.get('hyp') is hyp) or (poly is not None and track.get('poly') is poly):
            return channel
    return None


def _repeated_view(collector,channel,selected):
    if collector.solver is None or channel is None:
        return False
    return any(np.linalg.norm(selected-old)<0.1 for old in collector.solver.tracks[channel]['views'])


@contextmanager
def active_hooks(collector):
    """Capture actual returned Q3 records / Q4 intermediates, once per policy."""
    import solver as policy
    import particles as hypothesis_module
    original_q3 = policy.next_view
    original_q4 = hypothesis_module.Hypotheses.next
    def q3(poly,current,*args,**kwargs):
        selected,records = original_q3(poly,current,*args,**kwargs)
        points = np.array([record[1] for record in records])
        chosen = int(np.flatnonzero(np.all(points==selected,axis=1))[0])
        channel = _target_channel(collector,poly=poly)
        state = collector.capture(poly,None,current,points,planner_kind='q3_active',
            candidate_current_scores={i:r[0] for i,r in enumerate(records)},score_direction='min',
            chosen_index=chosen,move_times=np.array([r[3] for r in records]),
            metadata=dict(target_channel=channel,repeat_view_guard_would_override=_repeated_view(collector,channel,selected),
                          current_formula='original sampled D_worst + lambda * move_time',
                          original_policy_calls=1))
        if state is not None:
            for row,record in zip(state['candidate_records'],records):
                row['original_planner_D_worst'] = float(record[2])
                row['original_planner_safe_1000m'] = bool(record[4])
        return selected,records
    def q4(hyp,poly,current):
        old_views,old_counts,old_next = hypothesis_module.candidate_views,hypothesis_module.signal_counts,hypothesis_module.next_view
        captured = {}
        def views(*a,**kw):
            value = old_views(*a,**kw);captured['points']=value.copy();return value
        def counts(*a,**kw):
            value = old_counts(*a,**kw);captured['counts']=value.copy();return value
        def next_view(*a,**kw):
            value = old_next(*a,**kw);captured['records']=copy.deepcopy(value[1]);return value
        hypothesis_module.candidate_views,hypothesis_module.signal_counts,hypothesis_module.next_view = views,counts,next_view
        try:
            selected = original_q4(hyp,poly,current)
        finally:
            hypothesis_module.candidate_views,hypothesis_module.signal_counts,hypothesis_module.next_view = old_views,old_counts,old_next
        points = captured['points']
        chosen = int(np.flatnonzero(np.all(points==selected,axis=1))[0])
        costs = np.linalg.norm(points-current,axis=1)/5+5
        channel = _target_channel(collector,hyp=hyp)
        scores = {}
        if len(hyp.p):
            probability = captured['counts']/max(1,len(hyp.p))
            uncertainty = np.array([record[2] for record in captured['records']])
            old_d = max(diameter(poly)[0],1e-6)
            gain = probability*np.maximum(0,1-uncertainty/old_d)+0.15*2*probability*(1-probability)
            scores = {i:float(score) for i,score in enumerate(gain/costs)}
            if chosen != int(np.argmax(list(scores.values()))):
                raise AssertionError('Captured Q4 intermediates do not reproduce its original selection')
        state = collector.capture(poly,hyp.p,current,points,planner_kind='q4_active',
            candidate_current_scores=scores,score_direction='max',chosen_index=chosen,move_times=costs,
            metadata=dict(target_channel=channel,repeat_view_guard_would_override=_repeated_view(collector,channel,selected),
                current_formula='original [p*max(0,1-Dpred/Dold)+0.15*2*p*(1-p)]/move_time',
                original_policy_calls=1,score_source='captured original signal_counts and next_view records',
                no_score_reason='empty hypotheses selects first candidate' if not len(hyp.p) else None))
        if state is not None and 'records' in captured:
            for row,record in zip(state['candidate_records'],captured['records']):
                row['original_planner_D_worst'] = float(record[2])
        return selected
    policy.next_view,hypothesis_module.Hypotheses.next = q3,q4
    try:
        yield collector
    finally:
        policy.next_view,hypothesis_module.Hypotheses.next = original_q3,original_q4


@contextmanager
def record_hypothesis_rngs():
    """Keep RNG references after tracks are cleared; no extra RNG is created."""
    from particles import Hypotheses
    original = Hypotheses.__init__
    inventory = []
    def initialize(hyp,*args,**kwargs):
        original(hyp,*args,**kwargs)
        inventory.append((copy.deepcopy(args),copy.deepcopy(kwargs),hyp))
    Hypotheses.__init__ = initialize
    try:
        yield inventory
    finally:
        Hypotheses.__init__ = original


class StrictReplay:
    """Serve saved responses, requiring exact action/channel/coordinate equality."""
    def __init__(self,actions):
        self.records,self.index = actions,0
        self.position,self.channel,self.virtual_time,self.stage = np.zeros(2),1,0.,'discovery'
        self.actions = []
    def action(self,path,position=None,channel=None):
        if self.index>=len(self.records):
            raise AssertionError('Replay produced an extra action')
        record = self.records[self.index]
        actual = dict(path=path,position=np.asarray(position).tolist() if position is not None else None,channel=channel)
        expected = {key:record.get(key) for key in actual}
        if actual!=expected:
            raise AssertionError(f'Action {self.index} differs from frozen trace: {actual} != {expected}')
        self.index += 1
        self.virtual_time = record['response']['virtual_time_s']
        if position is not None:
            self.position = np.asarray(position).copy()
        if path=='/measure':
            self.channel = int(channel)
        self.actions.append(actual)
        return copy.deepcopy(record['response'])


def replay_trace(trace,config,shadow=False,max_states=None,max_scenarios=8,extra_hooks=None):
    """Replay one archived CPU case; off/on equality is checked by the caller.

    Every selected case captures all candidate-selection states by default.
    No core source is changed and no simulator is called.
    """
    from contextlib import ExitStack
    from phase_audit import TaggedSolver
    row = trace['row']
    if row.get('device','cpu')!='cpu':
        raise ValueError('This frozen shadow replay scope supports archived CPU traces only')
    api = StrictReplay(trace['actions'])
    solver = TaggedSolver(api,row['problem']==4,'P4' if row['problem']==4 else 'P3',
                          'cpu',config.get('particles',16384),diagnostic=config)
    collector = ShadowCollector(solver,max_states,max_scenarios)
    with ExitStack() as stack:
        inventory = stack.enter_context(record_hypothesis_rngs())
        if shadow:
            stack.enter_context(diagnostic_hook(collector))
            stack.enter_context(active_hooks(collector))
            if extra_hooks is not None:
                stack.enter_context(extra_hooks(collector))
        solver.run()
    if api.index!=len(api.records):
        raise AssertionError('Replay ended before consuming all archived actions')
    collector.finalize(api.actions)
    rng_inventory = [(args,kwargs,hyp.rng.bit_generator.state) for args,kwargs,hyp in inventory]
    return dict(actions=api.actions,actions_fingerprint=fingerprint(api.actions),
                solver_trace_fingerprint=fingerprint(solver.trace),
                solver_trace_excluded_fields=[],
                policy_rng_fingerprint=fingerprint((random.getstate(),np.random.get_state(),rng_inventory)),
                hypothesis_rng_creation_count=len(inventory),
                virtual_time=api.virtual_time,states=collector.states,skipped=collector.skipped,
                scope='q3_active_q4_active_depth_one_diagnostic_v1')


def compare_shadow_replays(off,on):
    keys = ('actions_fingerprint','solver_trace_fingerprint','solver_trace_excluded_fields',
            'policy_rng_fingerprint','hypothesis_rng_creation_count','virtual_time')
    mismatches = [key for key in keys if off[key]!=on[key]]
    if mismatches:
        raise AssertionError('Shadow mode changed frozen policy semantics: '+','.join(mismatches))
    return dict(passed=True,compared=keys,actions_count=len(off['actions']),
                actions_fingerprint=off['actions_fingerprint'],policy_rng_fingerprint=off['policy_rng_fingerprint'],
                solver_trace_excluded_fields=[],
                exclusion_reason='No trace fields are excluded; wall-clock timing is recorded outside policy traces')


def _load_trace(path):
    path = Path(path)
    if path.suffix=='.gz':
        with gzip.open(path,'rt',encoding='utf-8') as file:
            return json.load(file)
    return json.loads(path.read_text(encoding='utf-8'))


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _runtime_sources():
    paths = [*BASE.glob('*.py'), *BASE.glob('directional/*.py'), Path(__file__)]
    return {str(path.relative_to(BASE)):_file_sha(path) for path in paths}


def _atomic_json(path,value,compressed=False):
    """A killed run leaves only a disposable .partial, never a false checkpoint."""
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_name(path.name+'.partial')
    opener = gzip.open if compressed else open
    with opener(temporary,'wt',encoding='utf-8') as file:
        json.dump(value,file,ensure_ascii=False,allow_nan=False)
    temporary.replace(path)


def run_plan(plan_path,output,max_scenarios=None):
    """Serial checkpointed replay; hooks are deliberately process-local.

    ponytail: one saved case at a time avoids concurrent monkeypatching. The
    original plan fixes the cases; every selection state in each case is kept.
    Failed attempts remain in failures/ and may be retried by the same command.
    """
    plan_path,output = Path(plan_path),Path(output)
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    jobs = plan['jobs']
    max_scenarios = plan.get('shadow_max_scenarios',8) if max_scenarios is None else max_scenarios
    if max_scenarios!=plan.get('shadow_max_scenarios',8):
        raise ValueError('Scenario count differs from the frozen shadow plan')
    identities = [(job['problem'],job['seed'],job['variant']) for job in jobs]
    if len(set(identities))!=len(identities) or not jobs:
        raise ValueError('Frozen plan contains duplicate jobs or is empty')
    provenance = dict(schema='clearance-shadow-run-v1',plan_sha256=_file_sha(plan_path),
        source_hashes=_runtime_sources(),max_scenarios=max_scenarios,max_states=None,
        selection_rule=plan.get('selection_rule'),scope=plan.get('scope'),formal_runs=0)
    output.mkdir(parents=True,exist_ok=True)
    manifest_file = output/'RUN_MANIFEST.json'
    if manifest_file.exists():
        if json.loads(manifest_file.read_text(encoding='utf-8'))!=provenance:
            raise ValueError('Shadow plan or runtime source changed; use a new output directory')
    else:
        _atomic_json(manifest_file,provenance)
    completed,failures = [],[]
    for index,job in enumerate(jobs):
        case_name = f'q{job["problem"]}_{job["seed"]:04d}_{job["variant"]}'
        checkpoint = output/'cases'/f'{case_name}.json.gz'
        if _runtime_sources()!=provenance['source_hashes']:
            raise RuntimeError('Runtime source changed during shadow replay')
        if _file_sha(job['trace'])!=job['trace_sha256']:
            raise RuntimeError('Frozen trace hash mismatch: '+job['trace'])
        if checkpoint.exists():
            payload = _load_trace(checkpoint)
            if payload.get('job')!=job or payload.get('plan_sha256')!=provenance['plan_sha256'] or not payload.get('replay_integrity',{}).get('passed'):
                raise RuntimeError('Invalid existing shadow checkpoint: '+str(checkpoint))
        else:
            try:
                trace = _load_trace(job['trace'])
                if any(trace['row'][key]!=job[key] for key in ('problem','seed','variant')):
                    raise ValueError('Trace identity does not match the frozen job')
                off = replay_trace(trace,job['config'],False,None,max_scenarios)
                on = replay_trace(trace,job['config'],True,None,max_scenarios)
                integrity = compare_shadow_replays(off,on)
                if _runtime_sources()!=provenance['source_hashes']:
                    raise RuntimeError('Runtime source changed within case replay')
                payload = dict(job=job,plan_sha256=provenance['plan_sha256'],
                    replay_integrity=integrity,states=on['states'],skipped=on['skipped'],
                    evidence='offline saved-response policy replay; no simulator or HTTP',
                    generalization='case-enriched fixed audit subset; rates describe captured calls only')
                _atomic_json(checkpoint,payload,True)
            except Exception as exc:
                failure = dict(job=job,error=f'{type(exc).__name__}:{exc}',
                               plan_sha256=provenance['plan_sha256'])
                _atomic_json(output/'failures'/f'{case_name}_{time.time_ns()}.json',failure)
                failures.append(failure)
                print(f'{index+1}/{len(jobs)} FAILED {case_name}: {failure["error"]}',flush=True)
                continue
        completed.append(dict(case=case_name,path=str(checkpoint),sha256=_file_sha(checkpoint),
            states=len(payload['states']),skipped=len(payload['skipped']),
            action_count=payload['replay_integrity']['actions_count']))
        print(f'{index+1}/{len(jobs)} replay exact: {case_name}; states={len(payload["states"])}',flush=True)
    state_rows = []
    candidate_rows = []
    for case in completed:
        payload = _load_trace(case['path'])
        for state in payload['states']:
            identity = dict(case=case['case'],problem=payload['job']['problem'],variant=payload['job']['variant'],
                            seed=payload['job']['seed'],state=state['shadow_state_index'],planner_kind=state['planner_kind'])
            state_rows.append(dict(**identity,**{key:state.get(key) for key in (
                'candidate_count','current_score_count','current_score_unique_values','no_signal_candidate_count',
                'G_equals_current_count','G_unique_values','GAP_DEGENERATE_STATE','planner_selected_index',
                'shadow_G_rule_choice','min_move_time_choice','G_rule_matches_min_move_time',
                'G_rule_differs_from_planner','original_plan_accepted','original_grid_cost',
                'executed_planned_measurement','planner_point_equals_executed_point',
                'execution_override_detected','execution_override_reason')}))
            for candidate in state['candidate_records']:
                candidate_rows.append(dict(**identity,candidate_x=candidate['point'][0],candidate_y=candidate['point'][1],
                    **{key:value for key,value in candidate.items()
                                                        if key not in ('outcomes','point')}))
    for filename,rows in (('STATES.csv',state_rows),('CANDIDATES.csv',candidate_rows)):
        fields = list(dict.fromkeys(key for row in rows for key in row)) or ['case','state']
        with (output/filename).open('w',encoding='utf-8-sig',newline='') as file:
            writer = csv.DictWriter(file,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    groups = {}
    for kind in sorted({row['planner_kind'] for row in state_rows}):
        group = [row for row in state_rows if row['planner_kind']==kind]
        groups[kind] = dict(captured_states=len(group),gap_degenerate_states=sum(r['GAP_DEGENERATE_STATE'] for r in group),
                           gap_degenerate_state_rate=sum(r['GAP_DEGENERATE_STATE'] for r in group)/len(group))
    summary = dict(schema='clearance-shadow-summary-v1',plan_sha256=provenance['plan_sha256'],
        expected_cases=len(jobs),completed_cases=len(completed),failed_cases=failures,
        all_replays_exact=len(completed)==len(jobs) and not failures,
        all_states_captured=not any(case['skipped'] for case in completed),
        action_count=sum(case['action_count'] for case in completed),groups=groups,cases=completed,
        formal_runs=0,scope=plan.get('scope'),selection_rule=plan.get('selection_rule'),
        rates_are_population_estimates=False,source_unchanged=_runtime_sources()==provenance['source_hashes'])
    summary['passed'] = summary['all_replays_exact'] and summary['all_states_captured'] and summary['source_unchanged']
    _atomic_json(output/'SUMMARY.json',summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--trace',type=Path)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-states',type=int)
    parser.add_argument('--max-scenarios',type=int,default=8)
    args = parser.parse_args()
    if args.plan:
        if args.trace or args.config or args.max_states is not None:
            parser.error('--plan uses its frozen jobs and all states; do not override trace/config/state count')
        summary = run_plan(args.plan,args.output,args.max_scenarios)
        print(json.dumps({key:summary[key] for key in ('expected_cases','completed_cases','passed','groups')},indent=2))
        if not summary['passed']:
            raise SystemExit(2)
        return
    if not args.trace or not args.config:
        parser.error('Supply --plan, or both --trace and --config')
    if args.output.exists():
        raise FileExistsError('Use a new shadow output file; archived audit evidence is immutable')
    if args.trace.suffix=='.gz':
        with gzip.open(args.trace,'rt',encoding='utf-8') as file:
            trace = json.load(file)
    else:
        trace = json.loads(args.trace.read_text(encoding='utf-8'))
    config = json.loads(args.config.read_text(encoding='utf-8'))
    off = replay_trace(trace,config,False,args.max_states,args.max_scenarios)
    on = replay_trace(trace,config,True,args.max_states,args.max_scenarios)
    integrity = compare_shadow_replays(off,on)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    payload = dict(schema='clearance-shadow-v1',trace_sha256=hashlib.sha256(args.trace.read_bytes()).hexdigest(),
        config=config,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        selection_scope=dict(max_states=args.max_states,max_scenarios=args.max_scenarios,
                             planner='q3_active_q4_active_depth_one_diagnostic_v1'),
        replay_integrity=integrity,states=on['states'],skipped=on['skipped'],
        gap_degenerate_state_rate=(sum(s['GAP_DEGENERATE_STATE'] for s in on['states'])/len(on['states']) if on['states'] else None),
        evidence='offline frozen-response policy replay; no simulator or HTTP',
        generalization='Only the explicitly captured planner calls; not all Q4/active states or a calibrated probability')
    args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(replay_integrity=integrity,state_count=len(on['states']),gap_degenerate_state_rate=payload['gap_degenerate_state_rate']),indent=2))


if __name__=='__main__':
    main()
