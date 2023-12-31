#!/usr/bin/env python

import rospy
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Odometry
import math
import tf.transformations as tf
import actionlib
from actionlib_msgs.msg import *
from move_base_msgs.msg import *
from geometry_msgs.msg import Twist

###         CONSTANTS
MIN_GROUP_SIZE = 3
MAX_DIST_FOR_CONSECUTIVE_POINTS = 0.025
SPLIT_MERGE_TRESHOLD = 0.025
DOCK_ANGLE_TRESHOLD = 20
DOCK_LENGTH_TRESHOLD = 0.2
DOCK_POS_TRESHOLD = 0.2
DOCK_ROT_TRESHOLD = 20
DOCK_AIM_DISTANCE = 0.5
DOCK_STOP_DISTANCE = 0.2

rx = 0 # last known x pos of the robot
ry = 0 # last known y pos of the robot
rz = 0 # last known z rot of the robot

dockPoses = [] # detected poses of the dock
dockRots = [] # detected rotations of the dock
averageDockPos = None # average of the detected poses
averageDockRot = None # average of the detected rotations
targetDockPos = [0, 0] # the coordinates where we found the dock
targetDockRot = 0 # the rotation of the found dock
global sac # SimpleActionClient which we use to send goals to move_base node when we want the robot to use navigation
global velpub # Publisher that we publish to to send velocity messages over cmd_vel_mux/input/navi topic when we need to move the robot directly
zibitticikti = False # docked

def odomcb(msg):    # odometry callback function that updates the variables which hold robots axis
    global rx, ry, rz
    rx = msg.pose.pose.position.x
    ry = msg.pose.pose.position.y
    rz = math.degrees(tf.euler_from_quaternion([msg.pose.pose.orientation.x, msg.pose.pose.orientation.y, msg.pose.pose.orientation.z, msg.pose.pose.orientation.w])[2])
    pass

def distance(a, b):     # distance of two points
    return math.sqrt((b[0]-a[0])**2+(b[1]-a[1])**2)

def distanceToLine(p, a, b):    # distance of a point P to line [AB]
    d = distance(a, b)
    n = abs((b[0]-a[0])*(a[1]-p[1])-(a[0]-p[0])*(b[1]-a[1]))
    return n / d

def findFarthestTwoPoints(points):      # find most distant two points in a list of points
    maxdist = 0
    p3 = []
    p4 = []
    for i in range(len(points)):
        for j in range(i+1, len(points)):
            tempdist = distance(points[i], points[j])
            if tempdist > maxdist:
                maxdist = tempdist
                p3 = points[i]
                p4 = points[j]
    return [p3, p4]

def farthestPointToLine(points, a, b): # find the most distant point to the line [AB] from a list of points
    maxdist = 0
    farthestPoint = []
    for point in points:
        if (not a is point) and (not b is point):
            tempdist = distanceToLine(point, a, b)
            if tempdist>maxdist:
                maxdist = tempdist
                farthestPoint = point
    return [farthestPoint, maxdist]

def farthestPointToLine2(points, a, b): # same function as above but works better
    maxdist = 0
    farthestPoint = []
    for point in points:
        if not (a == point) and not (b == point):
            _a = point[0]-a[0]
            _b = point[1]-a[1]
            _c = b[0]-a[0]
            _d = b[1]-a[1]
            dot = _a*_c+_b*_d
            lsq = _c*_c+_d*_d
            p = -1
            if lsq != 0:
                p = dot/lsq
            if p < 0 or p > 1:
                continue
            dx = point[0] - a[0] - p * _c
            dy = point[1] - a[1] - p * _d
            dist = math.sqrt(dx*dx+dy*dy)
            if dist > maxdist:
                maxdist = dist
                farthestPoint = point
    return farthestPoint, maxdist

def split(recursion, lines, points, a, b):  # splits the line into multiple lines if its curved
    farthestPoint, maxdist = farthestPointToLine2(points, a, b)
    if maxdist > SPLIT_MERGE_TRESHOLD and recursion < 5:
        recursion+=1
        split(recursion, lines, points, farthestPoint, a)
        split(recursion, lines, points, farthestPoint, b)
    else:
        lines.append([a, b])

def lineMiddlePoint(line):  # find center of the line
    return [(line[1][0]+line[0][0])/2, (line[1][1]+line[0][1])/2]

def lineLength(line):   # calculate length of the line
    return math.sqrt((line[1][0]-line[0][0])**2+(line[1][1]-line[0][1])**2)

# !!! used only on lines which have a common point!
def commonPointOfTwoLines(l1, l2):  # find which end point of the lines is in common
    if l1[0] is l2[0]: return l1[0]
    if l1[0] is l2[1]: return l1[0]
    if l1[1] is l2[0]: return l1[1]
    if l1[1] is l2[1]: return l1[1]

def angleBetweenTwoLines(l1, l2):   # find the angle between two lines using dot product
    dot = (l1[1][0]-l1[0][0])*(l2[1][0]-l2[0][0])+(l1[1][1]-l1[0][1])*(l2[1][1]-l2[0][1])
    angle = math.degrees(math.acos(dot/lineLength(l1)/lineLength(l2)))
    return angle



### old function

# def checkLinesForDockInRealEnv(lines): 
#     #print(len(lines))
#     if len(lines)!=2: return
#     print(angleBetweenTwoLines(lines[0], lines[1]))

#     score = 0
#     lengths = [lineLength(lines[0]), lineLength(lines[1])]
#     angles = [angleBetweenTwoLines(lines[0], lines[1])]
#     requiredLengths = [0.40, 0.40]
#     requiredAngles = [135]

#     for i in range(len(requiredLengths)):
#         if abs(requiredLengths[i]-lengths[i])<DOCK_LENGTH_TRESHOLD: score+=1
#     for i in range(len(requiredAngles)):
#         if abs(requiredAngles[i]-angles[i])<DOCK_ANGLE_TRESHOLD: score+=1

#     if score >= 3: # yay we found the dock now we do the dockerinos
#         dockAt = commonPointOfTwoLines(lines[0], lines[1])
#         cOtherPoint = lines[1][0] if lines[1][1] is dockAt else lines[1][1]
#         bOtherPoint = lines[0][0] if lines[0][1] is dockAt else lines[0][1]
#         entrance = lineMiddlePoint([cOtherPoint, bOtherPoint])
#         dockAngle = angleBetweenTwoLines([dockAt, entrance], [dockAt, [dockAt[0]+1, dockAt[1]]])
#         dockAngle = math.degrees(math.atan2(entrance[1]-dockAt[1], entrance[0]-dockAt[0]))
#         dockFoundAt(dockAt, dockAngle)

### old function

# check if lines match our custom dock made of 4 lines and 3 angles
def checkLinesForDock(lines):
    print(len(lines))
    if len(lines)!=4: return
    a = []
    b = []
    c = []
    d = []
    maxdist = 0
    mpa = []
    mpd = []
    copy = lines[:]
    for i in range(4):
        for j in range(i, 4):
            mp1 = lineMiddlePoint(lines[i])
            mp2 = lineMiddlePoint(lines[j])
            dist = distance(mp1, mp2)
            if dist > maxdist:
                maxdist = dist
                mpa = mp1
                mpd = mp2
                a = lines[i]
                d = lines[j]
    copy.remove(a)
    copy.remove(d)
    d1 = distance(mpa, lineMiddlePoint(copy[0]))
    d2 = distance(mpa, lineMiddlePoint(copy[1]))
    if d1 < d2:
        b = copy[0]
        c = copy[1]
    else:
        b = copy[1]
        c = copy[0]

    score = 0
    lengths = [lineLength(a), lineLength(b), lineLength(c), lineLength(d)]
    angles = [angleBetweenTwoLines(a, b), angleBetweenTwoLines(b, c), angleBetweenTwoLines(c, d)]
    requiredLengths = [0.4, 0.4, 0.4, 0.4]
    requiredAngles = [150, 130, 150]

    for i in range(4):
        if abs(requiredLengths[i]-lengths[i])<DOCK_LENGTH_TRESHOLD: score+=1
    for i in range(3):
        if abs(requiredAngles[i]-angles[i])<DOCK_ANGLE_TRESHOLD: score+=1
	
    print("-")
    print(score)
    print(lengths)
    print(angles)
    if score > 6: # yay we found the dock now we do the dockerinos
        dockAt = commonPointOfTwoLines(b, c)
        cOtherPoint = c[0] if c[1] is dockAt else c[1]
        bOtherPoint = b[0] if b[1] is dockAt else b[1]
        entrance = lineMiddlePoint([cOtherPoint, bOtherPoint])
        dockAngle = angleBetweenTwoLines([dockAt, entrance], [dockAt, [dockAt[0]+1, dockAt[1]]])
        dockAngle = math.degrees(math.atan2(entrance[1]-dockAt[1], entrance[0]-dockAt[0]))
        dockFoundAt(dockAt, dockAngle)

def calculateAverageDock(dockAt, dockAngle):
    dockPoses.append(dockAt)
    dockRots.append(dockAngle)
    if len(dockPoses) > 50: dockPoses.pop(0)
    if len(dockRots) > 50: dockRots.pop(0)
    global averageDockPos, averageDockRot
    if averageDockPos is None:
        averageDockPos = dockAt
    else:
        averageDockPos = [sum(pos[0] for pos in dockPoses)/len(dockPoses), sum(pos[1] for pos in dockPoses)/len(dockPoses)]
    if averageDockRot is None:
        averageDockRot = dockAngle
    else:
        averageDockRot = sum(dockRots)/len(dockRots)

def dockFoundAt(dockAt, dockAngle):
    print("found dock at "+str(dockAt)+" "+str(dockAngle))
    calculateAverageDock(dockAt, dockAngle)
    if averageDockPos is None or averageDockRot is None or abs(averageDockPos[0]-targetDockPos[0]) > DOCK_POS_TRESHOLD or abs(averageDockPos[1]-targetDockPos[1]) > DOCK_POS_TRESHOLD or abs(averageDockRot-targetDockRot) > DOCK_ROT_TRESHOLD:
        print(averageDockPos is None)
        print(averageDockRot is None)
        print(averageDockPos[0])
        print(targetDockPos[0])
        print(abs(averageDockPos[0]-targetDockPos[0]) > DOCK_POS_TRESHOLD)
        print(abs(averageDockPos[1]-targetDockPos[1]) > DOCK_POS_TRESHOLD)
        print(abs(averageDockRot-targetDockRot) > DOCK_ROT_TRESHOLD)
        if len(dockPoses) > 20:
            updateDock()

def updateDock():
    global targetDockPos, targetDockRot
    targetDockPos = averageDockPos
    targetDockRot = averageDockRot
    print("updated dock")
    xx = DOCK_AIM_DISTANCE*math.cos(math.radians(targetDockRot))+targetDockPos[0]
    yy = DOCK_AIM_DISTANCE*math.sin(math.radians(targetDockRot))+targetDockPos[1]
    print("go to "+str(xx)+" "+str(yy)+" "+str(targetDockRot))
    state = -1
    # while state != 3:
    #     state = goToGoal(xx, yy, targetDockRot)
    manualGoTo(xx, yy, targetDockRot)
    # state = goToGoal(-3.8, 2, 0)
    state = 3
    if state == 3:
        print("start rotating")
        setRotation(targetDockRot)
    print("after rotation")
    xx = DOCK_STOP_DISTANCE*math.cos(math.radians(targetDockRot))+targetDockPos[0]
    yy = DOCK_STOP_DISTANCE*math.sin(math.radians(targetDockRot))+targetDockPos[1]
    manualGoToBackwards(xx, yy, targetDockRot)
    global zibitticikti
    zibitticikti = True
    print("done!")

def manualGoTo(x, y, z):
    xd = x-rx
    print("manual go to "+str(x))
    print(xd)
    yd = y-ry
    t = Twist()
    while(abs(xd)>0.05 or abs(yd)>0.05):
        dist = distance([x,y],[rx,ry])
        atan = math.atan2(yd, xd)
    asdasd = (atan-math.radians(rz))
    if asdasd > 1:
        asdasd = 1
        t.angular.z = asdasd
        t.linear.x = dist/5
        velpub.publish(t)
        xd = x-rx
        yd = y-ry
    t.angular.z = 0
    t.linear.x = 0
    velpub.publish(t)

def manualGoToBackwards(x, y, z):
    xd = x-rx
    print("backwards manual go to "+str(x))
    print(xd)
    yd = y-ry
    t = Twist()
    while(abs(xd)>0.1 or abs(yd)>0.1):
        dist = distance([x,y],[rx,ry])
        atan = math.atan2(yd, xd)
        t.angular.z = (atan-math.radians(rz+180))
        t.linear.x = -dist/5
        velpub.publish(t)
        xd = x-rx
        yd = y-ry
    t.angular.z = 0
    t.linear.x = 0
    velpub.publish(t)

def setRotation(r):
    print("set rotation "+str(r))
    dif = r-rz
    t = Twist()
    while(abs(dif)>2):
        asdasd = dif*0.75
        if asdasd > 10:
            asdads = 10
        t.angular.z = math.radians(asdasd)
        velpub.publish(t)
        dif = r-rz
    t.angular.z = 0
    velpub.publish(t)

def goToGoal(x, y, z):
    while not sac.wait_for_server(rospy.Duration.from_sec(5)):
        print("Attempting to connect to move_base node...")
    mbg = MoveBaseGoal()
    mbg.target_pose.header.frame_id = "map"
    mbg.target_pose.header.stamp = rospy.Time.now()
    mbg.target_pose.pose.position.x = x
    mbg.target_pose.pose.position.y = y
    mbg.target_pose.pose.position.z = 0
    q = tf.quaternion_from_euler(0, 0, z)
    mbg.target_pose.pose.orientation.x = q[0]
    mbg.target_pose.pose.orientation.y = q[1]
    mbg.target_pose.pose.orientation.z = q[2]
    mbg.target_pose.pose.orientation.w = q[3]
    sac.send_goal(mbg)
    sac.wait_for_result(rospy.Duration.from_sec(30))
    print(sac.get_state())
    return sac.get_state()

def analyzeGroup(points):
    lines = []
    farthestTwoPoints = findFarthestTwoPoints(points)
    split(0, lines, points, farthestTwoPoints[0], farthestTwoPoints[1])    
    checkLinesForDock(lines)
    #print(len(lines))


def scancb(msg):
    global zibitticikti
    if zibitticikti: return
    pointCount = len(msg.ranges)
    pointGroups = []
    previousPoint = None
    pointGroup = []
    firstPoint = None
    firstPointAssigned = False
    lastPoint = None
    for i in range(pointCount):
        r = msg.ranges[i]
        angle = i*math.degrees(msg.angle_increment)+rz
        if r==float('inf') or r > 2:
            if len(pointGroup)>MIN_GROUP_SIZE:
                pointGroups.append(pointGroup)
            pointGroup = []
            previousPoint = None
            firstPointAssigned = True
            continue
        x = math.cos(math.radians(angle))*msg.ranges[i]+rx
        y = math.sin(math.radians(angle))*msg.ranges[i]+ry
        currentPoint = [x, y]
        if i == pointCount-1:
            lastPoint = currentPoint
        if not firstPointAssigned:
            firstPoint = currentPoint
            firstPointAssigned = True
        if previousPoint == None:
            pointGroup.append(currentPoint)
            previousPoint = currentPoint
            continue
        else:
            if distance(currentPoint, previousPoint) > MAX_DIST_FOR_CONSECUTIVE_POINTS:
                if len(pointGroup)>MIN_GROUP_SIZE:
                    pointGroups.append(pointGroup)
                pointGroup = []
                continue
            pointGroup.append(currentPoint)
            previousPoint = currentPoint
    
    if firstPoint == None:
        if len(pointGroup)>MIN_GROUP_SIZE:
            pointGroups.append(pointGroup)
    else:
        if lastPoint is not None and distance(lastPoint, firstPoint) < MAX_DIST_FOR_CONSECUTIVE_POINTS:
            if len(pointGroups) > 0 and pointGroups[0][0] == firstPoint:
                pointGroups[0].extend(pointGroup)

#     print(len(pointGroups))

    for group in pointGroups:
        analyzeGroup(group)

if __name__=="__main__":
    rospy.init_node("dock")
    rospy.Subscriber("/scan", LaserScan, callback=scancb, queue_size=1)
    rospy.Subscriber("/odom", Odometry, callback=odomcb)
    sac = actionlib.SimpleActionClient("/move_base", MoveBaseAction)
    velpub = rospy.Publisher("/cmd_vel_mux/input/navi", Twist, queue_size=10)
    state = 0
    print("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    #while state != 3:
     #   state = goToGoal(1, 1.75, 0)
    rospy.spin()