# ros-docking
Detection of dev specified shape and docking on it.

Robot searches for nearby shapes using Split and Merge algorithm on coordinates of end points of the laser beams fired by a lidar sensor.
If the found shapes match our dock, the robot gets close to the dock and stops right in front of it, aligning itself to the normal line of it, then it goes backwards and stops inside the dock.
