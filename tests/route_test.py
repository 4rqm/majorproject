import sys
import os 

sys.path.append("../server")

from core.route import *

from mock_data.data_generation import data_generation
import json

location = Point(-33.8796735,151.2053924)
vert_unit,hor_unit = Route.get_coordinate_units(location)
bounding_box = Route.rectangle_bounding_box(location,1000,1000)
# Creates test json files
# data_generation(bounding_box)

with open('mock_data/ways.json') as f:
    waydata = json.load(f)

with open('mock_data/nodes.json') as f:
    nodedata = json.load(f)

ways = Way.json_to_ways(waydata)
nodes = Node.json_to_nodes(nodedata)

tag_keys = set()
nodes_with_tags = [n for n in nodes.values() if n.tags]

for node in nodes_with_tags:
    for tag in node.tags:
        tag_keys.add(tag)

print(tag_keys)

start_id = 8109379
end_id   = 8109400

print(nodes[8109379])


# route = Route.generate_route(nodes, ways, start_id, end_id)
# print(nodes[start_id] - nodes[end_id])
# print(route.route, route.distance)
