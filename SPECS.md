# LayerNester

LayerNester is a Blender 5.2 addon to manage visibility of nested objects.

Each Object that has a child can have layer nester enabled or disabled. Disabled by default.

When user enables it, there will be an integer slider for each level of the nest. For example

Parent
    Child Group 1
        Child 1
    Child Group 2
        Child 2
        Child 3
    Child 4


There will be two sliders.

And these sliders can be adjusted so that only one Child is visible at a time.

For the above example. To make:
1. Child 1 visible
    Slider 1: 1
    Slider 2: 1

2. Child 3 visible:
    Slider 1: 2
    Slider 2: 2

3. Child 4 visible:
    Slider 1: 3
    Slider 2: 0


The amount of slider should not be dynamic. it should use the highest amount of nest in the group
    
