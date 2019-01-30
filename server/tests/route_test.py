import sys
import os

sys.path.append("../server")
from core.route import *

from mock_data.data_generation import data_generation
import json

location = Point(-33.8796735,151.2053924)
vert_unit,hor_unit = Route.get_coordinate_units(location)
bounding_box = Route.rectangle_bounding_box(location,1000,1000)
# data_generation(bounding_box)

with open('mock_data/ways.json') as f:
    way_data = json.load(f)

with open('mock_data/nodes.json') as f:
    node_data = json.load(f)

nodes, ways = Route.transform_json_nodes_and_ways(node_data,way_data)

start_id = 8109379
end_id   = 8109400


route = Route.generate_route(nodes, ways, start_id, end_id)
print(route.route, route.distance)
