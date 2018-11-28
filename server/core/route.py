from __future__ import annotations
import math
import copy
import json
from math import inf

EARTH_RADIUS = 6371000 #In metres

class Point:
    """
    Represents a geodetic point with latitude and longitude

    Attributes
    ----------
    latitude : float
        A floating point value in degrees representing latitude
    longitude : float
        A floating point value in degrees representing longitude
    """

    def __init__(self, *coords: float or str):
        latitude, longitude = coords if len(coords) > 1 else coords[0].split(',')
        self.latitude = float(latitude)
        self.longitude = float(longitude)

    def distance(self, other: Point) -> int:
        """
        Uses spherical geometry to calculate the surface distance between two points.

        Parameters
        ----------
        other : Point
            Another point object to calculate the distance against

        Returns
        -------
        int
            The calculated distance in kilometers
        """

        lat1, lon1 = self
        lat2, lon2 = other

        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)

        a = (
            math.sin(dlat / 2)
            * math.sin(dlat / 2)
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2)
            * math.sin(dlon / 2)
            )

        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return EARTH_RADIUS * c

    def heuristic_distance(self, other: Point, hor_unit, vert_unit):
        delta_lat = abs(self.latitude - other.latitude)
        delta_lon = abs(self.longitude - other.longitude)
        x_dist = hor_unit * delta_lon
        y_dist = vert_unit * delta_lat
        return x_dist**2 + y_dist**2

    def __iter__(self):
        return iter((self.latitude, self.longitude))

    def __sub__(self, other) -> int:
        """
        Another way to call the distance function
        >>> point1 - point2
        69
        """
        return self.distance(other)


class Node:
    def __init__(self, point: Point, id: str):
        self.id = id
        self.point = point
        self.ways = set()

    def __eq__(self, other: Point):
        return self.id == other.id

    @staticmethod
    def json_to_nodes(json_nodes):
        nodes = json_nodes['elements']
        formatted_nodes = {node['id']: Node.from_json(node) for node in nodes}
        return formatted_nodes

    @classmethod
    def from_json(cls, nodedata: dict) -> Node:
        position = Point(nodedata['lat'], nodedata['lon'])
        return cls(position, nodedata['id'])

    def closest_node(self, nodes: dict) -> Node:
        """Returns the closest node from a list of nodes"""
        nodes = sorted(nodes.values(), key=lambda n: n.point - self.point)
        closest_node = nodes[0]
        return closest_node

class Way:
    def __init__(self, nodes: list, id: str, tags):
        self.nodes = nodes
        self.id = id
        self.tags = tags

    @classmethod
    def from_json(cls, way: dict):
        tags = way['tags'] if 'tags' in way else {}
        return cls(way['nodes'], way['id'], tags)

    @staticmethod
    def json_to_ways(json_ways):
        ways = json_ways['elements']
        formatted_ways = {way['id']:Way.from_json(way) for way in ways}
        return formatted_ways

class Route:
    def __init__(self, route: list, distance: int, routeID=None):
        self.route = route
        self.distance = distance
        self.id = None #ID in database

    @property
    def json(self):
        return {
            "success": True,
            "route": self.route,
            "dist": self.distance,
            "id": self.id
        }

    @staticmethod
    def get_coordinate_units(location):
        '''
        Coordinate unit in terms of metres for localized area
        '''
        latitude,longitude = location
        vert_unit = location - Point(latitude,longitude + 1)
        hor_unit  = location - Point(latitude + 1,longitude)
        return vert_unit,hor_unit

    @classmethod
    def square_bounding(cls,length,width,location):
        latitude,longitude = location
        vert_unit,hor_unit = cls.get_coordinate_units(location)
        lat_unit = (width/2) / hor_unit
        lon_unit = (length/2) / vert_unit
        la1 = latitude - lat_unit
        lo1 = longitude - lon_unit
        la2 = latitude + lat_unit
        lo2 = longitude + lon_unit
        bounding_coords = ','.join(list(map(str,[la1,lo1,la2,lo2])))
        return bounding_coords

    @staticmethod
    def find_neighbours(ways: dict) -> dict:
        """
        Generates neighbours for every node in provided ways
        """
        neighbours = {}
        for way in ways.values():
            way_nodes = way.nodes
            for index, node in enumerate(way_nodes):
                node_neighbours = set()
                if (index - 1) > 0: node_neighbours.add(way_nodes[index - 1])
                if (index + 1) < len(way_nodes): node_neighbours.add(way_nodes[index + 1])
                if node not in neighbours:
                    neighbours[node] = set()
                neighbours[node] |= node_neighbours
        return neighbours

    @classmethod
    async def from_database(cls,db,routeID):
        """
        Creates a route object from a route stored in the database
        """
        route = await db.find_one({'id_':routeID})
        return cls(routeID, **route['route'])

    @classmethod
    def generate_route(cls, nodes: dict, ways: dict, start_id: int, end_id: int, preferences: dict=None) -> Route:
        """
        Generates the shortest route to a destination
        Uses A* with euclidean distance as heuristic
        Uses tags to change cost of moving to nodes
        """
        unvisited = set(node_id for node_id in nodes)
        visited = set()
        path_dict = dict((node,(inf,[node])) for node in nodes)
        neighbours = cls.find_neighbours(ways)
        path_dict[start_id] = (0,[start_id])
        vert_unit,hor_unit = cls.get_coordinate_units(nodes[start_id].point)
        end_point = nodes[end_id].point

        if end_id not in nodes: raise Exception('End node not in node space. Specify a valid node.')
        elif start_id not in nodes: raise Exception('End node not in node space. Specify a valid node.')
        elif end_id not in neighbours or start_id not in neighbours: raise Exception('No connecting neighbour')
        else: current = start_id

        while True:
            current_point = nodes[current].point
            current_cost,current_path = path_dict[current]
            current_neighbours = neighbours[current]
            for neighbour in current_neighbours:
                if neighbour in unvisited:
                    neighbour_cost,neighbour_path = path_dict[neighbour]
                    neighbour_point = nodes[neighbour].point
                    heuristic_distance = current_point.heuristic_distance(neighbour_point,vert_unit,hor_unit)
                    tag_cost = 0 #heuristic_distance * sum(preferences[tag] for tag in neighbour_tags)
                    new_cost = heuristic_distance + current_cost + tag_cost
                    if new_cost < neighbour_cost:
                        path_dict[neighbour] = (new_cost,current_path + [neighbour])
            unvisited.remove(current)
            visited.add(current)
            if end_id in visited: break
            else:
                min_cost,next_node = inf, None
                for node_id in unvisited:
                    current_distance,path = path_dict[node_id]
                    current_point = nodes[node_id].point
                    heuristic_distance = end_point.heuristic_distance(current_point,vert_unit,hor_unit)
                    current_cost = current_distance + heuristic_distance
                    if current_cost < min_cost: min_cost,next_node = current_cost,node_id
                if min_cost == inf: raise Exception("End node cannot be reached")
                else: current = next_node

        heuristic_cost, fastest_route = path_dict[end_id]
        route_points = [nodes[node_id].point for node_id in fastest_route]
        actual_distance = sum(route_points[index]-route_points[index+1] for index in range(len(route_points)-1))
        return cls(fastest_route,actual_distance)

    async def save_route(self, db, userid):
        #Adds to database of routes
        document = {
            "author":userid,
            "route":{
                "route":self.route,
                "distance":self.distance,
                }
            }
        self.id = await db.routes.insert_one(document).inserted_id

if __name__ == '__main__':
    pass
