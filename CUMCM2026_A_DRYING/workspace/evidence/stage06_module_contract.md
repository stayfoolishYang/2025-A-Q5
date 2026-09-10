# Stage06 temporary implementation coordination contract

Authority: A26-04-v2; explicit user Stage06 confirmation received. This records code interfaces, not new mathematics. PERFORMANCE. Parent owns integration and official artifacts.

- `src/drying/inputs.py`, `config.py`, `tests/test_inputs.py`: input worker only.
- `src/drying/physics.py`, `spatial.py`, `manufactured.py`, `tests/test_spatial.py`: numerical core worker only.
- `src/drying/reconstruction.py`, `events.py`, `export.py`, `tests/test_output.py`: output worker only.
- All other files (integrator, trajectory/checkpoints, diagnostics, CLI, pipeline, configs, manifests, docs and publication): parent only.

Interfaces agreed before parallel edits:

* State: float64 array flattened from `(nr,nz,2)` with last axis `[T_K,C_kgkg]`; B uses nz=1, C physical half-axis [0,ell=.125].
* `Grid(nr,nz=1,route='B')`: attributes nr,nz,route,ncell,size,xi,xi_faces,omega,z,z_faces,dz; `dry_weights` is flattened per-cell weights summing 1; `volumes(R)` returns flattened full-domain cell volumes (C doubles half-volume). Exact volume centroids.
* `properties(question,T,C)` -> Material attributes a,k,D,a_C,k_C,D_C,D_T; vectorized. question 1,23,4. `surface(U,env,A,b,delta)` -> (U_surface,outward_flux,beta), shared reconstruction/operator formula.
* `Inputs(data_dir,scenario='S0',radius_method='linear',radius_tail='NONE',window_start_h=3.0)`. `.at(t,question=23,geometry='fixed',side='point')` -> dataclass Boundary(T_inf,C_eq,R,Rdot). `.nodes(question=23,geometry='fixed',tmax=259200)` sorted input-node times excluding 0. `.node_kind(t,question=23,geometry='fixed')` -> JUMP/KINK/NONE. `.fingerprint` string. Raw portable bundle data/raw/environment.xlsx,radius.xlsx,templates/result1..4.xlsx,source_manifest.json (hashes).
* `DryingSystem(grid,inputs,question=23,geometry='fixed',end_condition='C0',test_case=None,h=25.,hm=8e-7)`. attrs grid,inputs,question,geometry,end_condition,h,hm. `.initial()` flattened state. `.evaluate(t,y,side='point',jacobian=True)` -> Eval with f,jac (csc or None),water (unit dry),water_out (unit dry/s),heat_out (W),source_water,source_heat, a(flat cells), volumes(flat cells), and optional face arrays. `.rhs(t,y,side='point')` convenience f. Physical validity/scales handled by integrator. Formal TEST_CASE None; MMS object supplies constants/averaged source/boundary values.
* `reconstruct(system,t,y,side='point')` -> object with `.base_C` ndarray, `.max_C` float, `.max_position` tuple(xi,z), `.query(r_m,z_m=0)` -> (T_K,C), `.surface(z_m=0)` -> (T_K,C). Must guard positivity/coverage and use all nodes. Can add helper APIs.
* Events: pure functions for affine base-node strict interval intersection; trajectory scanner operates ordered `(t,y)` segments plus system; no made-up error margin. Parent drives required reintegration and evidence/config refinement. Export consumes parent trajectory `.iter_segments()` yielding `(t0,y0,t1,y1)` and `.at(t)` (raises outside coverage); `.start_time`, `.end_time`. Export requires supplied accepted event record for q23/q4; q1 fixed full1800 permitted after developer validation. File publication atomic after readback.
* Integrator generic system `.evaluate` contract; sparse linear algebra, custom BDF2/BE. No solve_ivp BDF. Checkpoint stored by parent. Tests import `drying` via PYTHONPATH=src or conftest.

Workers must report interface deviations before integration, do not modify other's files, do not write official Gate/state, and do not perform long problem runs. Small module tests are allowed. No recursive agents.
