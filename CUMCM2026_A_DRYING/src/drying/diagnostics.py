"""Independent accepted-path water and effective-heat balances, section 6.7/16.

Tdot is the accepted trajectory secant, never the operator RHS. The heat
diagnostic is an effective-rate balance, not full thermodynamic conservation.
"""
from __future__ import annotations
import numpy as np


class Diagnostics:
    def __init__(self,system,tmax,settings,state=None):
        self.system=system; self.tmax=float(tmax); self.cfg=settings
        initial=system.evaluate(0,system.initial(),jacobian=False)
        self.W0=initial.water
        self.heat_scale0=float(np.sum(initial.volumes*initial.a))
        self.data=state or {'water_integral':0.,'heat_residual':0.,'heat_flux_abs':0.,
            'heat_rate_abs':0.,'water_max_abs':0.,'water_max_relative':0.,
            'heat_max_abs':0.,'heat_max_relative':0.,'water_quadrature_error':0.,
            'heat_quadrature_error':0.,'quadrature_evaluations':0,
            'quadrature_unresolved':False,'layer_water_max':0.,'layer_heat_max':0.,
            'layer_bound_violations':0,'segments':0,'covered_until':0.}

    def add_segment(self,t0,y0,t1,y1,info=None,raw_residual=None):
        h=t1-t0; tdot=(y1[0::2]-y0[0::2])/h
        cache={}
        def integrand(frac):
            if frac not in cache:
                t=t0+frac*h; y=y0+frac*(y1-y0)
                side='right' if frac==0 else ('left' if frac==1 else 'point')
                ev=self.system.evaluate(t,y,side=side,jacobian=False)
                rate=float(np.sum(ev.volumes*ev.a*tdot))
                cache[frac]=np.array([ev.water_out-ev.source_water,
                    rate+ev.heat_out-ev.source_heat,abs(ev.heat_out),abs(rate)])
            return cache[frac]
        n=1; previous=h*(integrand(0.)+integrand(1.))/2
        budget_w=1e-6*self.W0*h/self.tmax
        budget_a=1e-5*self.heat_scale0*h/self.tmax
        delta=np.zeros(4)
        for _ in range(20):
            mids=sum((integrand((k+.5)/n) for k in range(n)),start=np.zeros(4))
            refined=previous/2+h/(2*n)*mids
            delta=abs(refined-previous)
            if delta[0]<=budget_w and delta[1]<=budget_a:
                previous=refined; break
            n*=2; previous=refined
        else: self.data['quadrature_unresolved']=True
        d=self.data
        d['quadrature_evaluations']+=len(cache)
        d['water_integral']+=float(previous[0]); d['heat_residual']+=float(previous[1])
        d['heat_flux_abs']+=float(previous[2]); d['heat_rate_abs']+=float(previous[3])
        d['water_quadrature_error']+=float(delta[0]); d['heat_quadrature_error']+=float(delta[1])
        ev=self.system.evaluate(t1,y1,side='left',jacobian=False)
        error_w=ev.water-self.W0+d['water_integral']
        heat_scale=max(self.heat_scale0,d['heat_flux_abs'],d['heat_rate_abs'])
        d['water_max_abs']=max(d['water_max_abs'],abs(error_w))
        d['water_max_relative']=max(d['water_max_relative'],abs(error_w)/self.W0)
        d['heat_max_abs']=max(d['heat_max_abs'],abs(d['heat_residual']))
        d['heat_max_relative']=max(d['heat_max_relative'],abs(d['heat_residual'])/heat_scale)
        if info is not None and raw_residual is not None:
            from .integrator import physical_scale
            weights=self.system.grid.dry_weights; volumes=ev.volumes
            psi_w=float(np.dot(weights,raw_residual[1::2]))
            psi_a=float(np.dot(volumes*ev.a,raw_residual[0::2]))
            scale=physical_scale(y1,y0,self.cfg); alpha0=info['alpha'][0]
            bound_w=alpha0*self.cfg.newton_tol*np.dot(weights,scale[1::2])
            bound_a=alpha0*self.cfg.newton_tol*np.dot(volumes*ev.a,scale[0::2])
            # Explicit, conservative engineering floating allowance, not a proof.
            abs_history=info['absolute_history']
            round_w=64*np.finfo(float).eps*(np.dot(weights,abs_history[1::2])+h*abs(ev.water_out)+h*abs(ev.source_water)+1)
            # Absolute side/end heat contributions prevent cancellation of faces.
            R=self.system.boundary(t1,'left').R
            g=self.system.grid
            heat_face_abs=float(np.sum(abs(ev.radial_flux[-1,:,0])*2*np.pi*R*2*g.dz))
            if g.route=='C':
                heat_face_abs+=float(np.sum(abs(ev.axial_flux[:,-1,0])*4*np.pi*R**2*g.omega))
            round_a=64*np.finfo(float).eps*(np.dot(volumes*ev.a,abs_history[0::2])+h*heat_face_abs+h*abs(ev.source_heat)+self.heat_scale0)
            d['layer_water_max']=max(d['layer_water_max'],abs(psi_w))
            d['layer_heat_max']=max(d['layer_heat_max'],abs(psi_a))
            if abs(psi_w)>bound_w+round_w or abs(psi_a)>bound_a+round_a:
                d['layer_bound_violations']+=1
        d['segments']+=1; d['covered_until']=float(t1)
        d['water_final']=ev.water
        return self.summary()

    def summary(self):
        result=dict(self.data)
        result.update({'water_initial':self.W0,'heat_scale_initial':self.heat_scale0,
            'path_derivative':'ACCEPTED_STATE_SECANT_NOT_RHS',
            'water_budget_passed':self.data['water_max_relative']<=1e-5,
            'heat_budget_passed':self.data['heat_max_relative']<=1e-4,
            'evidence_scope':'DEVELOPMENT_EFFECTIVE_MODEL_BALANCE',
            'complete_thermodynamic_conservation_claimed':False})
        return result
