"""Strict affine-node event search; no fabricated uncertainty certification."""
from dataclasses import dataclass,asdict
from decimal import Decimal,ROUND_CEILING
import numpy as np
from .reconstruction import reconstruct,ReconstructionError
from .trajectory import fingerprint


@dataclass(frozen=True)
class StrictInterval:
    lower: float
    upper: float
    lower_open: bool
    upper_open: bool

    def as_dict(self):
        return asdict(self)


def affine_strict_interval(v0,v1,threshold=.15):
    a,b = np.broadcast_arrays(np.asarray(v0,float),np.asarray(v1,float))
    if a.size==0 or np.any(~np.isfinite(a)) or np.any(~np.isfinite(b)) or not np.isfinite(threshold):
        raise ValueError("EVENT_UNRESOLVED: nonfinite affine nodes/threshold")
    lo,hi,lop,hip = 0.,1.,False,False
    for x,d in zip(a.ravel(),(b-a).ravel()):
        if d==0:
            if x>=threshold:
                return None
            continue
        cut=float((threshold-x)/d)
        if d<0:
            if cut>lo:
                lo,lop=cut,True
            elif cut==lo:
                lop=True
        else:
            if cut<hi:
                hi,hip=cut,True
            elif cut==hi:
                hip=True
        if lo>=hi:
            return None
    if hi<=0 or lo>=1:
        return None
    return StrictInterval(lo,hi,lop,hip)


def upward_report_time(t_eligible):
    if not np.isfinite(t_eligible) or t_eligible<0:
        raise ValueError("invalid eligible time")
    q=Decimal(".36")
    return float((Decimal(str(t_eligible))/q).to_integral_value(rounding=ROUND_CEILING)*q)


def scan_events(system,trajectory,threshold=.15,checked_until=None,strict_retention=True):
    """Inspect all accepted segments in order; candidate is never certification.

    Completeness is limited to the prescribed affine base-node reconstruction
    and formal environments below the requested threshold. Re-integration,
    refined comparisons and the error/report-time protocol belong to caller.
    """
    result={"status":"NO_EVENT", "threshold":float(threshold), "t_hat":None,
            "tL":None,"tR":None,"candidate_segment":None,"checked_until":float(trajectory.start_time),
            "earliest_verified":trajectory.start_time==0 or checked_until==trajectory.start_time,
            "retention_verified":False,"rebound":False,"reconstruction":"O1_O2_AFFINE_BASE",
            "issues":[],"segments_checked":0}
    if system.test_case is not None:
        result.update(status="EVENT_UNRESOLVED",earliest_verified=False)
        result["issues"].append("Formal boundary-convexity shortcut disabled for TEST_CASE; use affine_strict_interval for isolated tests")
        return result
    if threshold <= max(float(np.max(system.inputs.water)),system.inputs.tail_water):
        result.update(status="ERROR_BUDGET_UNRESOLVED",earliest_verified=False)
        result["issues"].append("Threshold not strictly above all environment values")
        return result
    seen=False
    expected=float(trajectory.start_time)
    for t0,y0,t1,y1 in trajectory.iter_segments():
        if t0!=expected or not t1>t0:
            result["issues"].append("Earlier trajectory gap/nonincreasing segment")
            result["earliest_verified"]=False
        expected=float(t1)
        try:
            a=reconstruct(system,t0,y0,side="right")
            b=reconstruct(system,t1,y1,side="point")
            interval=affine_strict_interval(a.base_C,b.base_C,threshold)
        except (ReconstructionError,ValueError) as exc:
            result["issues"].append(str(exc))
            result["earliest_verified"]=False
            if seen: result["rebound"]=True
            continue
        result["segments_checked"]+=1
        result["checked_until"]=float(t1)
        if interval is not None:
            if result["t_hat"] is None:
                h=t1-t0
                strict_theta=interval.upper if not interval.upper_open else (interval.lower+interval.upper)/2
                result.update(t_hat=float(t0+h*interval.lower),tL=float(t0),tR=float(t0+h*strict_theta),
                              candidate_segment=[float(t0),float(t1)],interval=interval.as_dict())
            if seen and (interval.lower>0 or interval.lower_open):
                result["rebound"]=True
            seen=True
            if interval.upper<1 or interval.upper_open:
                result["rebound"]=True
        elif seen:
            result["rebound"]=True
    if result["t_hat"] is not None:
        result["status"]="PROVISIONAL_EVENT"
    if result["issues"] or (strict_retention and result["rebound"]):
        result["status"]="EVENT_UNRESOLVED"
    result["retention_verified"]=bool(seen and not result["rebound"] and not result["issues"])
    return result


def verify_report(system,trajectory,record):
    """Check caller-supplied *measured* error evidence and actual report state."""
    if record.get("status")!="DRYING_COMPLETE":
        raise ValueError("REPORT_TIME_UNRESOLVED: DRYING_COMPLETE required")
    if not record.get("earliest_verified") or not record.get("retention_verified"):
        raise ValueError("EVENT_UNRESOLVED: earlier coverage or retention unresolved")
    ev=record.get("error_evidence",{})
    if not ev.get("checks_passed") or not ev.get("refinement_verified"):
        raise ValueError("ERROR_BUDGET_UNRESOLVED: error/refinement evidence required")
    for name in ("eC","eG","eT","et","coverage_end"):
        if name not in ev or not np.isfinite(ev[name]) or ev[name]<0:
            raise ValueError(f"ERROR_BUDGET_UNRESOLVED: missing/invalid {name}")
    for name in ("t_hat","tL","tR","t_plus","t_minus","t_eligible","et_ref","level_time_uncertainty","report_delay"):
        if name not in record or not np.isfinite(record[name]) or record[name]<0:
            raise ValueError(f"ERROR_BUDGET_UNRESOLVED: missing/invalid {name}")
    if not record["tL"]<=record["t_hat"]<=record["tR"] or record["tR"]-record["tL"]>.0100000001:
        raise ValueError("EVENT_UNRESOLVED: refined nominal bracket invalid")
    if not record["t_plus"]<=record["t_hat"]<=record["t_minus"]:
        raise ValueError("EVENT_UNRESOLVED: threshold perturbation order")
    level=max(record["t_hat"]-record["t_plus"],record["t_minus"]-record["t_hat"])
    roundoff=64*np.finfo(float).eps*max(1.,record["t_minus"])
    if abs(record["level_time_uncertainty"]-level)>roundoff:
        raise ValueError("ERROR_BUDGET_UNRESOLVED: inconsistent level-time sensitivity")
    required_et=max(record["et_ref"],level)+record["tR"]-record["tL"]
    if ev["et"]+roundoff<required_et:
        raise ValueError("ERROR_BUDGET_UNRESOLVED: time error omits refinement or conditioning")
    if ev["eT"]>.05 or max(ev["eC"],ev["eG"])>.0005 or ev["et"]>.1*min(.01*record["t_hat"],1800.):
        raise ValueError("ERROR_BUDGET_UNRESOLVED: prescribed numerical budget exceeded")
    if (not ev.get("run_ids") or not ev.get("config_fingerprint")
            or ev.get("config_fingerprint")!=trajectory.index.get("identity",{}).get("config")
            or ev.get("trajectory_fingerprint")!=fingerprint(trajectory.index)):
        raise ValueError("ERROR_BUDGET_UNRESOLVED: error evidence identity does not match trajectory")
    t,eta=record.get("t_report"),record.get("eta_strict")
    if t is None or eta is None or not np.isfinite(t) or not np.isfinite(eta) or eta<=0:
        raise ValueError("REPORT_TIME_UNRESOLVED: invalid report time or margin")
    if Decimal(str(t))%Decimal(".36") != 0:
        raise ValueError("REPORT_TIME_UNRESOLVED: report time not on 0.36-second display grid")
    if not trajectory.start_time<=t<=trajectory.end_time or ev["coverage_end"]<t:
        raise ValueError("REPORT_TIME_UNRESOLVED: report/error coverage missing")
    if (upward_report_time(record["t_eligible"])!=t or record["t_eligible"]>t
            or abs(record["report_delay"]-(t-record["t_hat"]))>roundoff
            or not -roundoff<=record["t_eligible"]-record["t_minus"]<=.01+roundoff):
        raise ValueError("REPORT_TIME_UNRESOLVED: inconsistent report delay")
    required=max(2*max(ev["eC"],ev["eG"]),64*np.finfo(float).eps)
    if eta<required:
        raise ValueError("ERROR_BUDGET_UNRESOLVED: strict margin below empirical evidence")
    if .15-eta<=max(float(np.max(system.inputs.water)),system.inputs.tail_water):
        raise ValueError("ERROR_BUDGET_UNRESOLVED: tightened threshold does not admit formal convexity shortcut")
    r=reconstruct(system,t,trajectory.at(t))
    if not r.max_C+eta<.15:
        raise ValueError("REPORT_TIME_UNRESOLVED: full-node strict inequality failed")
    return {"t_report":float(t),"max_C":r.max_C,"max_position":r.max_position,
            "eta_strict":float(eta),"strict_sum":r.max_C+eta,"coverage_end":trajectory.end_time}
