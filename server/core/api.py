import asyncio
import functools

from sanic import Blueprint, response
from sanic.exceptions import abort
from sanic.log import logger

from core.route import Route, Point, Node, Way
from core.models import Overpass, Color, User
from core.decorators import jsonrequired, memoized, authrequired

api = Blueprint('api', url_prefix='/api')

cache = {}

@api.get('/route/multiple')
@memoized
async def multiple_route(request):
    """
    Api Endpoint that returns a multiple waypoint route
    Jason Yu/Abdur Raqueeb
    """

    data = request.args

    location_points = [Point.from_string(waypoint) for waypoint in data['waypoints']]

    path_euclidean_distance = Route.get_route_distance(location_points)
    if path_euclidean_distance > 50000: #50km
        return response.json({'success': False, 'message': "Route too long."})

    bounding_box = Route.bounding_points_to_string(Route.convex_hull(location_points))

    nodes_endpoint = Overpass.NODE.format(bounding_box) #Generate url to query api
    ways_endpoint = Overpass.WAY.format(bounding_box)

    print("Nodes Endpoint: " + nodes_endpoint)
    print("Ways Endpoint: " + ways_endpoint)

    tasks = [
        request.app.fetch(nodes_endpoint),
        request.app.fetch(ways_endpoint)
        ]

    node_data, way_data = await asyncio.gather(*tasks)

    nodes, ways = Route.transform_json_nodes_and_ways(node_data,way_data)
    way_node_ids = Way.get_way_node_ids(ways)

    waypoints = [point.closest_way_node(nodes, way_node_ids) for point in location_points]
    waypoint_ids = [node.id for node in waypoints]

    partial = functools.partial(Route.generate_multi_route, nodes, ways, waypoint_ids)
    route = await request.app.loop.run_in_executor(None, partial)
    return response.json(route.json)



# @authrequired
@api.get('/route')
@memoized
async def route(request):
    """
    Api Endpoint that returns a route
    Jason Yu/Abdur Raqueeb
    """
    data = request.args
    
    start = Point.from_string(data.get('start'))
    end = Point.from_string(data.get('end'))

    euclidean_distance = start - end
    if euclidean_distance > 50000: #50km
        return response.json({'success': False, 'message': "Route too long."})

    bounding_box = Route.bounding_points_to_string(Route.two_point_bounding_box(start, end))

    endpoint = Overpass.REQ.format(bounding_box) #Generate url to query api
    task = request.app.fetch(endpoint)

    print('getting data')
    data = await asyncio.gather(task)
    data = data[0]
    print('successfuly got data')

    node_data = []
    while data["elements"][0]["type"] == "node":
        node_data.append(data["elements"].pop(0))
    way_data = data["elements"]

    nodes, ways = Route.transform_json_nodes_and_ways(node_data,way_data)
    way_node_ids = Way.get_way_node_ids(ways)

    start_node = start.closest_way_node(nodes, way_node_ids)
    end_node = end.closest_way_node(nodes, way_node_ids)

    print("Start Node: " + str(start_node.id))
    print("End Node: " + str(end_node.id))

    partial = functools.partial(Route.generate_route, nodes, ways, start_node.id, end_node.id)

    route = await request.app.loop.run_in_executor(None, partial)

    return response.json(route.json)

@authrequired
@api.patch('/users/<user_id:int>')
async def update_user(request, user_id):
    """
    Change user information
    Abdur Raqueeb
    """
    data = request.json
    token = request.token
    password = data.get('password')
    user_id = jwt.decode(token, request.app.secret)['sub']
    user = await request.app.users.find_account(user_id=user_id)
    salt = bcrypt.gensalt()
    user.credentials.password = bcrypt.hashpw(password, salt)
    await user.update()
    return response.json({'success': True})

@api.delete('/users/<user_id:int>')
@authrequired
async def delete_user(request, user_id):
    """
    Deletes user from database
    Abdur Raqueeb
    """
    user = await request.app.users.find_account(user_id=user_id)
    await user.delete()
    return response.json({'success': True})

@api.post('/register')
@jsonrequired
async def register(request):
    """
    Register a user into the database
    Abdur Raqueeb
    """
    user = await request.app.users.register(request)
    return response.json({'success': True})

@api.post('/login')
@jsonrequired
async def login(request):
    """
    Logs in user into the database
    Abdur Raqueeb
    """
    data = request.json
    email = data.get('email')
    password = data.get('password')
    query = {'credentials.email': email}
    account = await request.app.users.find_account(**query)
    if account is None:
        abort(403, 'Credentials invalid.')
    elif account.check_password(password) == False:
        abort(403, 'Credentials invalid.')
    token = await request.app.users.issue_token(account)
    resp = {
        'success': True,
        'token': token.decode("utf-8"),
        'user_id': account.id
    }
    return response.json(resp)
