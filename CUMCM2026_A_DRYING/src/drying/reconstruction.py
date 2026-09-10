"""A26-04-v2 O1/O2: explicit nonconservative output reconstruction.

Cell-average states remain authoritative for the solver and balances. This
module never clips extrapolated nodes or replaces their maxima by cell maxima.
"""
from decimal import Decimal, localcontext
import math
import numpy as np
from .physics import T0, C0, ELL, surface


class ReconstructionError(ValueError):
    pass


class OutsideDomainError(ReconstructionError):
    pass


def base_nodes(grid, y):
    """Linear map from cell means to centres + true axis/midplane nodes."""
    u = np.asarray(y, dtype=np.float64).reshape(grid.nr, grid.nz, 2)
    m = (grid.xi_faces[:-1]**2 + grid.xi_faces[1:]**2)/2
    axis = (m[1]*u[0]-m[0]*u[1])/(m[1]-m[0])
    radial = np.concatenate((axis[None, :, :], u), axis=0)
    if grid.route == "B":
        return radial
    z = grid.z_faces
    mz = (z[1:]**3-z[:-1]**3)/(3*grid.dz)
    mid = (mz[1]*radial[:, 0]-mz[0]*radial[:, 1])/(mz[1]-mz[0])
    return np.concatenate((mid[:, None, :], radial), axis=1)


def _axis_extra(values, moments):
    return (moments[1]*values[0]-moments[0]*values[1])/(moments[1]-moments[0])


def _radius_exact(system, t):
    """High precision source-defined radius, only needed for close comparisons."""
    with localcontext() as ctx:
        ctx.prec = 60
        td = Decimal(str(t))
        if system.test_case is not None:
            if system.test_case.moving:
                return Decimal(".02")*(1-Decimal(".1")*td/Decimal("1000"))
            return Decimal(".02")
        if system.geometry == "fixed":
            return Decimal(".02")
        inp = system.inputs
        if td > 259200:
            if inp.radius_tail != "HOLD":
                raise OutsideDomainError("INPUT_HORIZON_REACHED")
            return Decimal(str(inp.radius_cm[-1]))/100
        i = min(max(int(td//1800), 0), len(inp.radius_cm)-2)
        vals = [Decimal(str(v))/100 for v in inp.radius_cm]
        h = Decimal(1800)
        u = (td-i*h)/h
        if inp.radius_method == "linear":
            return vals[i]+u*(vals[i+1]-vals[i])
        slopes = [(vals[j+1]-vals[j])/h for j in range(len(vals)-1)]
        def endpoint(a, b):
            m = (3*a-b)/2
            if m*a <= 0:
                return Decimal(0)
            if a*b < 0 and abs(m)>3*abs(a):
                return 3*a
            return m
        ms = [endpoint(slopes[0], slopes[1])]
        ms.extend(Decimal(0) if a*b<=0 else 2/(1/a+1/b) for a,b in zip(slopes[:-1],slopes[1:]))
        ms.append(endpoint(slopes[-1],slopes[-2]))
        return ((2*u**3-3*u**2+1)*vals[i]+(u**3-2*u**2+u)*h*ms[i]
                +(-2*u**3+3*u**2)*vals[i+1]+(u**3-u**2)*h*ms[i+1])


class Reconstruction:
    def __init__(self, system, t, y, side="point"):
        self.system, self.t, self.side = system, float(t), side
        grid = system.grid
        state = np.asarray(y, dtype=np.float64)
        if state.shape != (grid.size,):
            raise ReconstructionError("RECONSTRUCTION_UNRESOLVED: state shape")
        self.base = base_nodes(grid, state)
        if np.any(~np.isfinite(self.base)) or np.any(self.base[...,0]<=0) or np.any(self.base[...,1]<=0):
            raise ReconstructionError("RECONSTRUCTION_UNRESOLVED: nonfinite/nonpositive base node")
        self.envelope_excess = {"T": 0., "C": 0.}
        if system.test_case is None:
            rtol = getattr(system, "reconstruction_rtol", 1e-6)
            at = getattr(system, "reconstruction_atol_t", 1e-6)
            ac = getattr(system, "reconstruction_atol_c", 1e-9)
            for eq, lo, hi, atol, baseline, name in [(0,T0,323.396,at,T0,"T"),(1,.01963,C0,ac,0.,"C")]:
                v = self.base[...,eq]
                scale = atol+rtol*np.abs(v-baseline)
                excess = np.maximum(np.maximum(lo-v,v-hi),0.)
                self.envelope_excess[name] = float(excess.max())
                if np.any(excess>10*scale):
                    raise ReconstructionError(f"RECONSTRUCTION_UNRESOLVED: {name} base-node envelope")
        self.base_C = self.base[...,1].copy()
        self.boundary = system.boundary(t, side)
        self.R = self.boundary.R
        self.xi = np.r_[0.,grid.xi,1.]
        self.z = np.array([0.]) if grid.route == "B" else np.r_[0.,grid.z,ELL]
        nrad, nax = len(self.xi),len(self.z)
        self.nodes = np.empty((nrad,nax,2),dtype=np.float64)
        if grid.route == "B":
            self.nodes[:-1,0] = self.base[:,0]
        else:
            self.nodes[:-1,:-1] = self.base
        side_env,end_env = system.boundary_environments(t,side)
        if grid.route == "C":
            # MMS face environments are averages. Extend their quadratic
            # dependency with the same exact average-to-axis map, not a formal
            # S0 environment or unrelated material table.
            mz = (grid.z_faces[1:]**3-grid.z_faces[:-1]**3)/(3*grid.dz)
            mr = (grid.xi_faces[1:]**2+grid.xi_faces[:-1]**2)/2
            se = np.vstack((_axis_extra(side_env,mz),side_env))
            ee = np.vstack((_axis_extra(end_env,mr),end_env))
        else:
            se = side_env
        adjacent = self.base[-1]
        mat = system.material(adjacent[:,0],adjacent[:,1])
        for eq,A,b in [(0,mat.k,system.h),(1,mat.D,system.hm)]:
            self.nodes[-1,:len(se),eq] = surface(adjacent[:,eq],se[:,eq],A,b,self.R*(1-grid.xi[-1]))[0]
        if grid.route == "C":
            adjacent = self.base[:,-1]
            mat = system.material(adjacent[:,0],adjacent[:,1])
            for eq,A,b in [(0,mat.k,system.h),(1,mat.D,system.hm)]:
                be = b if system.end_condition == "C1" else 0.
                self.nodes[:-1,-1,eq] = surface(adjacent[:,eq],ee[:,eq],A,be,ELL-grid.z[-1])[0]
            cell = state.reshape(grid.nr,grid.nz,2)[-1,-1]
            mc = system.material(cell[0],cell[1])
            if system.test_case is None:
                environment = np.array([self.boundary.T_inf,self.boundary.C_eq])
            else:
                # Specified MMS perturbation vanishes at the exposed corner;
                # its two exact boundary environments meet at the background.
                environment = np.array([system.test_case.T_b,system.test_case.C_b])
            for eq,A,b in [(0,mc.k,system.h),(1,mc.D,system.hm)]:
                beta_r = float(surface(cell[eq],environment[eq],A,b,self.R*(1-grid.xi[-1]))[2])
                beta_z = float(surface(cell[eq],environment[eq],A,b if system.end_condition=="C1" else 0.,ELL-grid.z[-1])[2])
                self.nodes[-1,-1,eq] = environment[eq]+beta_r*beta_z*(cell[eq]-environment[eq])
        self.initial_semantics = "RIGHT_LIMIT_FLUX" if t == 0 else "ACCEPTED_RECONSTRUCTION"
        if t == 0 and side == "point" and system.test_case is None and np.array_equal(state,system.initial()):
            self.nodes[:,:,:] = (T0,C0)
            self.initial_semantics = "INITIAL_STATE"
        if np.any(~np.isfinite(self.nodes)) or np.any(self.nodes[...,0]<=0) or np.any(self.nodes[...,1]<=0):
            raise ReconstructionError("RECONSTRUCTION_UNRESOLVED: invalid exposed node")
        pos = np.unravel_index(np.argmax(self.nodes[...,1]),self.nodes.shape[:2])
        self.max_C = float(self.nodes[pos][1])
        self.max_position = (float(self.xi[pos[0]]),float(self.z[pos[1]]))

    def domain_relation(self,r_m):
        r = float(r_m)
        if not math.isfinite(r) or r < 0:
            raise OutsideDomainError("OUTSIDE_DOMAIN: negative/nonfinite radius")
        if abs(r-self.R) > 1e-13:
            return -1 if r < self.R else 1
        exact = _radius_exact(self.system,self.t)
        rd = Decimal(str(r_m))
        return -1 if rd<exact else (1 if rd>exact else 0)

    @staticmethod
    def _interval(nodes, value):
        if value == nodes[-1]:
            return len(nodes)-2,1.
        i = min(max(int(np.searchsorted(nodes,value,side="right")-1),0),len(nodes)-2)
        if i==0:
            weight = (value/nodes[1])**2
        else:
            weight = (value-nodes[i])/(nodes[i+1]-nodes[i])
        return i,float(weight)

    def query(self,r_m,z_m=0):
        rel = self.domain_relation(r_m)
        if rel>0:
            raise OutsideDomainError("OUTSIDE_DOMAIN: radius exceeds current material")
        if not np.isfinite(z_m) or z_m<0 or z_m>ELL:
            raise OutsideDomainError("OUTSIDE_DOMAIN: z outside half-cylinder")
        x = 1. if rel==0 else float(r_m)/self.R
        if rel<0 and abs(float(r_m)-self.R)<=1e-13:
            with localcontext() as ctx:
                ctx.prec=60
                x=float(Decimal(str(r_m))/_radius_exact(self.system,self.t))
        return self._query_xi(x,float(z_m))

    def _query_xi(self,x,z):
        i,w = self._interval(self.xi,x)
        if self.system.grid.route=="B":
            value = (1-w)*self.nodes[i,0]+w*self.nodes[i+1,0]
        else:
            j,v = self._interval(self.z,z)
            value = ((1-w)*(1-v)*self.nodes[i,j]+w*(1-v)*self.nodes[i+1,j]
                     +(1-w)*v*self.nodes[i,j+1]+w*v*self.nodes[i+1,j+1])
        return float(value[0]),float(value[1])

    def surface(self,z_m=0):
        if not np.isfinite(z_m) or z_m<0 or z_m>ELL:
            raise OutsideDomainError("OUTSIDE_DOMAIN: z outside half-cylinder")
        return self._query_xi(1.,float(z_m))


def reconstruct(system,t,y,side="point"):
    return Reconstruction(system,t,y,side)
