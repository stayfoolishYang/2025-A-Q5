"""Only the destination of an already-selected polygon certified clear changes."""
import json
import numpy as np
from geometry import is_certified_clear_point
from tspn_benchmark import Observed
from tspn_geometry import choose,R_CERT

class NeighborhoodSolver(Observed):
    def clear_certified_polygon(self,c,center,radius):
        mode=self.diagnostic.get('tspn_mode','OFF')
        if mode=='OFF':return super().clear_certified_polygon(c,center,radius)
        poly=np.asarray(self.tracks[c]['poly'],float)
        start=np.asarray(self.api.position,float).copy();center=np.asarray(center,float)
        u=self.anchor();before=self.api.virtual_time;receiver=self.api.channel
        point,selection=choose(poly,start,center,radius,u,mode)
        # Independently check actual JSON-submitted coordinates using inherited certificate.
        wire=json.loads(json.dumps(dict(x=float(point[0]),y=float(point[1])),allow_nan=False))
        point=np.array([wire['x'],wire['y']])
        if not is_certified_clear_point(poly,point,R_CERT):raise RuntimeError('HARD_FAIL_WIRE_CERTIFICATE')
        distance=float(np.linalg.norm(point-start));md=float(np.linalg.norm(center-start))
        event=dict(selector=mode,start=start.tolist(),polygon=poly.tolist(),mec_center=center.tolist(),mec_radius=float(radius),point=point.tolist(),clearance_radius=R_CERT,max_vertex_distance=float(np.linalg.norm(poly-point,axis=1).max()),travel_m=distance,mec_travel_m=md,same_state_saving_m=md-distance,zero_move=bool(distance==0),selection=selection,time_before=before,verification_status='TSPN_HARD_VERTEX_VERIFIED',submitted_position=wire,json_roundtrip_verified=True,next_mandatory_anchor=None if u is None else u.tolist(),receiver_before=receiver,**selection)
        self.target_trace(c).setdefault('certified_clearance_events',[]).append(event)
        success=self.clear(c,point,certified=True)
        event.update(success=bool(success),time_after=self.api.virtual_time,receiver_after=self.api.channel)
        return success
