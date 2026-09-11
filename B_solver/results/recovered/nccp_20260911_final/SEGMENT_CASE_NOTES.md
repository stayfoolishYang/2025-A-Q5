# 新增沿原路清除方案：最大退步案例复核

本文件只读比对已完成轨迹，没有追加模拟或参数调整。以下阶段差均为候选减参考的整局秒数；秒/源另列。局部同状态节省不等于实际两条轨迹的证书段差，也不能抵消后续路径放大。

## Q3，原256集合 seed 7

11源均清除。MEC / NCCP / segment 分别为 **329.193829 / 631.890080 / 809.141777 秒/源**。segment 比 MEC 多 **479.947948 秒/源**，比 NCCP 多 **177.251697 秒/源**。

| 阶段差/秒 | segment − MEC | segment − NCCP |
|---|---:|---:|
| discovery | +62.493430 | −0.965114 |
| active localization | −301.307972 | +0.334741 |
| diagnostic | 0 | 0 |
| optical fallback | +5412.925805 | +1948.828002 |
| certified clear | +105.316161 | +1.571035 |
| 合计 | +5279.427424 | +1949.768664 |

NCCP 与 segment 都因频道1连续无信号触发一次光学兜底；123个候选网格中均访问96个点，95次光学失败后成功。两者访问的点集合完全相同，顺序有50/96个位置不同，从第11个光学动作（全局0-based action 146）开始分叉。两方案均106次clear、diagnostic为0。

NCCP 光学段为 **15870.489045 m / 3464.097803 s**，segment 为 **25614.629041 m / 5412.925805 s**；多 **9744.139997 m**。两者该阶段固定光学/清除费用均290 s，时间差来自移动。

进入兜底前 action 135 的频道2清除落点相距 **5.087105 m**。冻结Q3配置的 `local_order=False` 沿用 `directional/fallback_cost.py` 对全部点按兜底起点距离一次排序；实际初始距离序列也符合该规则。起点微变、径向排序变化及折返路程增长，构成这例的观察性机制解释。没有做单独干预实验，不能把相关步骤扩大成普遍因果保证。本轮没有修改该既有排序。

segment 自身证书状态累计直接节省仅 **90.230186 m = 18.046037 s**。固定下一站两段不劣并不约束后续重新生成的整段访问顺序。

## Q4，原256集合 seed 210

12源均清除。MEC / NCCP / segment 分别为 **914.466043 / 972.738608 / 972.896569 秒/源**。segment 相比 MEC 多 **58.430525 秒/源**，整局多 **701.166305 s / 5005.831521 m**。

| 阶段 | segment − MEC/秒 |
|---|---:|
| discovery | −5.726062 |
| active localization | +856.012290 |
| diagnostic | 0 |
| optical fallback | 0 |
| certified clear | −149.119923 |

主动定位的主要增加在频道20（+518.968159 s）、频道12（+173.959780 s）、频道3（+172.748755 s）。三方案均无diagnostic、无fallback、clear均12次，不能把该例解释成恢复循环。NCCP与segment的请求类型、阶段、频道序列和清除顺序相同，坐标不同；segment仅比NCCP多1.895530秒整局。

segment 自身状态直接节省 **111.951115 m**；其真实证书段为 **1083.956855 m**，比MEC少 **745.599614 m**。后续主动定位增加覆盖了证书段改善。此处是完整轨迹的阶段归因，不是定位评分已被修改。

## 读数精度和证据入口

快照表的 `stored_center_error_m` 统一六位小数时显示0.000000，不是精确零：Q3最大 **3.843244215e−13 m**，Q4最大 **2.803368228e−13 m**。精细上界使用独立有理数支持圆，未把带1e−8裕量的代码半径当作精确MEC。

以下row/trace哈希摘自通过审计的三方案CSV，完整动作含下一动作、坐标及频道，可逐项复核。

### Q4 seed 210 mec_center

- row_path: `J:\2026B_experiments\nccp_20260911\holdout256\q4\rows\P4_diagnostic_v1_grid_v1_0210.json`
- row_sha256: `6126517cfd81d0bc1055c50a5a20d10fb7f951456ad1dc84065de0e848440464`
- trace_path: `J:\2026B_experiments\nccp_20260911\holdout256\q4\traces\P4_diagnostic_v1_grid_v1_0210.json.gz`
- trace_sha256: `e25ba4015d5d7ba9d5e29729d4ff3a39fa48084ed0b566fb77019533e53687a8`

### Q4 seed 210 nccp

- row_path: `J:\2026B_experiments\nccp_20260911\holdout256\q4\rows\P4_diagnostic_v1_grid_v1_nccp_0210.json`
- row_sha256: `ca71b970abc629b59d4544f2dfd2147360f66a8a40a84e6191ce6bbe2652cb58`
- trace_path: `J:\2026B_experiments\nccp_20260911\holdout256\q4\traces\P4_diagnostic_v1_grid_v1_nccp_0210.json.gz`
- trace_sha256: `47f32464b73b7e7a3781dac4ceb8cb8a685a633f419778188bd4f3f4576e601e`

### Q4 seed 210 segment_entry

- row_path: `J:\2026B_experiments\nccp_20260911\segment_extension\holdout256\q4\rows\P4_diagnostic_v1_grid_v1_segment_entry_0210.json`
- row_sha256: `8d797e97d0bca293c1e5f50572b46a0d6c3037fd2694499fced2f56952b0cfff`
- trace_path: `J:\2026B_experiments\nccp_20260911\segment_extension\holdout256\q4\traces\P4_diagnostic_v1_grid_v1_segment_entry_0210.json.gz`
- trace_sha256: `3d533697ee2d97045687df1144319f45830e5668320daede36945fe8adb3e348`

### Q3 seed 7 mec_center

- row_path: `J:\2026B_experiments\nccp_20260911\holdout256\q3\rows\P3_current_grid_v1_0007.json`
- row_sha256: `7328c09e239d4120334ddf087921bfadfe89b7f9d6bcc02895483a38b523dc65`
- trace_path: `J:\2026B_experiments\nccp_20260911\holdout256\q3\traces\P3_current_grid_v1_0007.json.gz`
- trace_sha256: `ce701cf174b1e14beec99419e13812aced358c721a86d846b11e45a9b7fca7a9`

### Q3 seed 7 nccp

- row_path: `J:\2026B_experiments\nccp_20260911\holdout256\q3\rows\P3_current_grid_v1_nccp_0007.json`
- row_sha256: `3bebcdaf3c61fa6f68771965db4813703ae96f0c36335ee9ad6fa18cb1b3fbf7`
- trace_path: `J:\2026B_experiments\nccp_20260911\holdout256\q3\traces\P3_current_grid_v1_nccp_0007.json.gz`
- trace_sha256: `0c3e552449c63db2da911072cfb4a62e14bbc38a875541959d2f856140e17357`

### Q3 seed 7 segment_entry

- row_path: `J:\2026B_experiments\nccp_20260911\segment_extension\holdout256\q3\rows\P3_current_grid_v1_segment_entry_0007.json`
- row_sha256: `8a29e337a7ec5b4e1b25641a9a9387befe69618e7584d828beb195d6788530c7`
- trace_path: `J:\2026B_experiments\nccp_20260911\segment_extension\holdout256\q3\traces\P3_current_grid_v1_segment_entry_0007.json.gz`
- trace_sha256: `088695d83ef59015b032bc21cd288158b174e02a9149c56d486cb30d5d5839fb`

