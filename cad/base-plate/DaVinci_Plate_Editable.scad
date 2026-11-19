// All dimensions in millimeters. Origin: bottom-left of plate, viewed from above.
// Blank by default: add measured mount coordinates only after a physical fit check.
plate_width = 220;
plate_depth = 285;
plate_thickness = 10;
mounts = []; // [[x1,y1], [x2,y2], [x3,y3]]
shaft_clearance_diameter = 0; // REQUIRED measurement before adding mounts
head_recess_diameter = 5.5; // provisional: user's head estimate 5 mm + 0.5 mm total clearance
head_recess_depth = 5; // user's approximate measurement; confirm before cutting
$fn = 96;
assert(plate_thickness > head_recess_depth);
assert(len(mounts) == 0 || shaft_clearance_diameter > 0,
       "Measure and set shaft_clearance_diameter before adding mount positions.");
assert(len(mounts) == 0 || head_recess_diameter > shaft_clearance_diameter);
for (p = mounts) {
    assert(p[0] > head_recess_diameter/2 && p[0] < plate_width-head_recess_diameter/2);
    assert(p[1] > head_recess_diameter/2 && p[1] < plate_depth-head_recess_diameter/2);
}
difference() {
    cube([plate_width, plate_depth, plate_thickness]);
    for (p = mounts) {
        translate([p[0],p[1],-0.1])
            cylinder(h=plate_thickness+0.2, d=shaft_clearance_diameter);
        translate([p[0],p[1],plate_thickness-head_recess_depth])
            cylinder(h=head_recess_depth+0.1, d=head_recess_diameter);
    }
}
