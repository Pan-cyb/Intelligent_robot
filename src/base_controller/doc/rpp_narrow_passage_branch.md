# RPP Narrow Passage Branch

This branch returns to Regulated Pure Pursuit after DWB testing showed strong sensitivity to the final goal point in narrow passages.

## Why RPP

DWB samples short local trajectories and scores them with both path and goal critics. In the narrow passage tests, changing the final goal point changed whether the robot could pass, even when the global path looked reasonable in RViz. That behavior is consistent with DWB's local optimization objective.

RPP is closer to a path tracking controller: it follows a carrot point on the global path. This should reduce sensitivity to the final goal point while preserving the terminal rotation behavior tuned in `tune/rpp-goal-rotation`.

## Changes

The lidar range filtering that worked during DWB tests is carried over:

```yaml
ld06.range_min: 0.12
amcl.laser_min_range: 0.12
local_costmap.obstacle_layer.scan.obstacle_min_range: 0.12
global_costmap.obstacle_layer.scan.obstacle_min_range: 0.12
```

The lidar driver also filters LaserScan and PointCloud data outside `[range_min, range_max]` to NaN instead of only publishing the limits as metadata.

RPP initially used a more conservative narrow-passage setup:

```yaml
desired_linear_vel: 0.20
lookahead_dist: 0.30
min_lookahead_dist: 0.22
max_lookahead_dist: 0.45
lookahead_time: 0.5
use_regulated_linear_velocity_scaling: true
use_cost_regulated_linear_velocity_scaling: true
regulated_linear_scaling_min_radius: 0.35
regulated_linear_scaling_min_speed: 0.08
```

That setup passed the difficult segment, but later testing showed turn motion felt stop-and-go. The likely cause was curvature-based velocity regulation plus a short lookahead, which made RPP reduce linear speed too aggressively while turning.

Local costmap inflation is relaxed to preserve usable local space:

```yaml
local_costmap.inflation_layer.inflation_radius: 0.20
local_costmap.inflation_layer.cost_scaling_factor: 8.0
global_costmap.inflation_layer.inflation_radius: 0.30
```

`controller_frequency` is set to 10 Hz and `expected_planner_frequency` to 5 Hz to match observed compute limits on the robot.

## Test Focus

In RViz, check whether the local costmap leaves a usable corridor at the previous failure location.

If RPP tracks through the same segment with less dependence on the final goal point, DWB should be abandoned for this robot/map combination.

If RPP still fails while the local costmap corridor is visibly open, the repeated `STM communicate lost...` warnings should be investigated next because stale odometry can trigger `Failed to make progress` independently of controller choice.

## Turn Smoothness Update

Initial RPP testing passed the narrow passage and terminal rotation worked, but turns could feel stop-and-go. The likely cause is cost-regulated velocity scaling reacting to local costmap values near inflated obstacles. In narrow corridors, small scan/costmap changes can repeatedly reduce and release linear speed.

The first smoothness update kept curvature-based velocity regulation but disabled cost-based linear regulation:

```yaml
lookahead_dist: 0.34
min_lookahead_dist: 0.26
max_lookahead_dist: 0.55
max_allowed_time_to_collision_up_to_carrot: 0.8
use_regulated_linear_velocity_scaling: true
use_cost_regulated_linear_velocity_scaling: false
regulated_linear_scaling_min_speed: 0.10
```

The slightly longer lookahead should reduce steering jitter, while curvature regulation still slows the robot for tight turns.

Further comparison with commit `b2aae44` showed the smoother behavior came from the original RPP motion profile: longer lookahead and no regulated linear velocity scaling. This branch therefore restores those motion-profile parameters while keeping the useful fixes from this branch, such as 0.12 m lidar filtering, smaller local inflation, and the terminal rotation tuning:

```yaml
desired_linear_vel: 0.26
lookahead_dist: 0.45
min_lookahead_dist: 0.35
max_lookahead_dist: 0.70
lookahead_time: 0.6
use_regulated_linear_velocity_scaling: false
use_cost_regulated_linear_velocity_scaling: false
regulated_linear_scaling_min_radius: 0.45
regulated_linear_scaling_min_speed: 0.12
```

## Collision Prediction Update

The restored motion profile still showed stop-and-go turns in field logs. The relevant controller warning was:

```text
RegulatedPurePursuitController detected collision ahead!
```

RPP projects the current command forward for collision checking. In a narrow inflated corridor, a long projection window can repeatedly touch inflated cells even when the visible global path is valid, causing the controller to stop and resume. This branch keeps collision checking enabled but shortens the prediction window:

```yaml
use_collision_detection: true
max_allowed_time_to_collision_up_to_carrot: 0.35
```

Field testing still showed repeated `detected collision ahead` warnings with a 0.35 s window. For the next controlled test, this branch disables RPP's forward collision projection while keeping the costmap obstacle/inflation layers and global planning obstacle checks active:

```yaml
use_collision_detection: false
max_allowed_time_to_collision_up_to_carrot: 0.35
```
