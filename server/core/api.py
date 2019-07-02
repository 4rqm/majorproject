import asyncio
import functools
import bson
import dateutil.parser

from io import BytesIO

from sanic import Blueprint, response
from sanic.exceptions import abort
from sanic.log import logger

from core.route_generation import Route, Point, Node, Way
from core.route import RealTimeRoute, RunningSession, SavedRoute, RecentRoute
from core.misc import Overpass, Color
from core.user import User
from core.decorators import jsonrequired, memoized, authrequired


api = Blueprint("api", url_prefix="/api")

locationCache = {}

"""
Route API Calls (Single, Multiple)
"""


@api.get("/route")
@memoized
async def route(request):
    """
    Api Endpoint that returns a route
    Jason Yu/Abdur Raqueeb/Sunny Yan
    """
    data = request.args
    # Generate Bounding Box
    start = Point.from_string(data.get("start"))
    end = Point.from_string(data.get("end"))
    # Check Valid Distance
    min_euclidean_distance = start - end
    if min_euclidean_distance > 50000:  # 50km
        return response.json({"success": False, "error_message": "Route too long."})
    bounding_box = Route.bounding_points_to_string(
        Route.two_point_bounding_box(start, end)
    )
    endpoint = Overpass.REQ.format(bounding_box)  # Generate url to query api
    # Fetch Node Data and Way Data
    task = request.app.fetch(endpoint)
    data = await asyncio.gather(task)  # Data is array with response as first element
    elements = data[0]["elements"]  # Nodes and Ways are together in array in json
    node_data, way_data = [], []
    for element in elements:
        if element["type"] == "node":
            node_data.append(element)
        elif element["type"] == "way":
            way_data.append(element)
        else:
            raise Exception("Unidentified element type")
    # Generate Route
    nodes, ways = Route.transform_json_nodes_and_ways(node_data, way_data)
    start_node = start.closest_node(nodes)
    end_node = end.closest_node(nodes)
    partial = functools.partial(
        Route.generate_route, nodes, ways, start_node.id, end_node.id
    )
    route = await request.app.loop.run_in_executor(None, partial)
    return response.json(route.json)


@api.get("/route/multiple")
@memoized
async def multiple_route(request):
    """
    Api Endpoint that returns a multiple waypoint route
    Jason Yu/Abdur Raqueeb/Sunny Yan
    """
    data = request.args
    # Generate Locations and Bounding Box
    location_points = [Point.from_string(waypoint) for waypoint in data["waypoints"]]
    min_euclidean_distance = Route.get_route_distance(location_points)
    # Check Valid Distance
    if min_euclidean_distance > 50000:  # 50km
        return response.json({"success": False, "error_message": "Route too long."})
    bounding_box = Route.bounding_points_to_string(Route.convex_hull(location_points))
    endpoint = Overpass.REQ.format(bounding_box)  # Generate url to query api
    # Fetch Node Data and Way Data
    task = request.app.fetch(endpoint)
    data = await asyncio.gather(task)  # Data is array with response as first element
    elements = data[0]["elements"]  # Nodes and Ways are together in array in json
    node_data, way_data = [], []
    for element in elements:
        if element["type"] == "node":
            node_data.append(element)
        elif element["type"] == "way":
            way_data.append(element)
        else:
            raise Exception("Unidentified element type")
    # Generate Route
    nodes, ways = Route.transform_json_nodes_and_ways(node_data, way_data)
    waypoint_nodes = [point.closest_node(nodes) for point in location_points]
    waypoint_ids = [node.id for node in waypoint_nodes]
    partial = functools.partial(Route.generate_multi_route, nodes, ways, waypoint_ids)
    route = await request.app.loop.run_in_executor(None, partial)
    return response.json(route.json)


"""
Account API Calls
"""

@api.delete('/users/<user_id:int>')
@authrequired
async def delete_user(request, user, user_id):
    """
    Deletes user from database
    Abdur Raqueeb
    """
    await user.delete()
    return response.json({"success": True})


@api.post("/register")
@jsonrequired
async def register(request):
    """
    Register a user into the database, then logs in
    Abdur Raqueeb/Sunny Yan
    """
    user = await request.app.users.register(request)
    token = await request.app.users.issue_token(user)
    return response.json(
        {"success": True, "token": token.decode("utf-8"), "user_id": user.id}
    )



@api.post("/login")
@jsonrequired
async def login(request):
    """
    Logs in user into the database
    Abdur Raqueeb
    """
    data = request.json
    email = data.get('email')
    password = data.get('password')
    user = await request.app.users.find_account(**{'credentials.email': email})
    if user is None:
        abort(403, "Credentials invalid.")
    elif user.check_password(password) == False:
        abort(403, "Credentials invalid.")
    token = await request.app.users.issue_token(user)
    return response.json({
        'success': True,
        'token': token.decode("utf-8"),
        'user_id': user.id
    })
	
@api.post('/google_login')
@jsonrequired
async def google_login(request):
    """
    Registers or logs in with Google
    Sunny
    """
    idToken = request.json.get('idToken')
    request = request.app.fetch(
        "https://oauth2.googleapis.com/tokeninfo?id_token=" + idToken
    )
    resp = await asyncio.gather(request)
    print(resp)
    if resp.get("error"):
        abort(403,"Google token invalid")
    user = await request.app.users.find_account(**{'credentials.email': resp['email']})
    if user is None:
        user = request.app.users.register(
            {
                "json": {
                    "email": resp["email"],
                    "password": "<GOOGLE ONLY>",
                    "full_name": resp["name"],
                    "username": resp["email"],
                }
            }
        )
    token = await request.app.users.issue_token(user)
    resp = {"success": True, "token": token.decode("utf-8"), "user_id": user.id}
    return response.json(resp)


"""
Update Info API Calls
"""


@api.post("/save_route")
@jsonrequired
@authrequired
async def save_route(request, user):
    """
    Sends current Route of user
    Jason Yu
    """
    data = request.json
    name = data.get("name")
    description = data.get("description")
    # Retrieving user real time route
    real_time_route = user.real_time_route
    # Saving Route Image
    route_image = real_time_route.route.generateStaticMap()
    await request.app.db.images.insert_one({
        'user_id': user.id,
        'route_name': name,
        'route_image': route_image
    })
    saved_route = SavedRoute.from_real_time_route(name, description, route_image, real_time_route)
    new_point_total = user.stats.points + saved_route.points
    await user.set_to_dict_field('stats','points', new_point_total)
    await user.set_to_dict_field('saved_routes',saved_route.id,saved_route.to_dict())
    resp = {
        'success': True,
    }
    return response.json(resp)


@api.post("/save_recent_route")
@authrequired
async def save_recent_route(request, user):
    """
    Sends current location of user
    Jason Yu
    """
    recent_route = RecentRoute.from_real_time_route(user.real_time_route)
    new_point_total = user.stats.points + recent_route.points
    await user.set_to_dict_field('stats','points', new_point_total)
    await user.push_to_field('recent_routes',recent_route.to_dict())
    resp = {
        'success': True,
    }
    return response.json(resp)


@api.post("/follow")
@authrequired
@jsonrequired
async def follow(request, user):
    """
    Follows user
    Jason Yu
    """
    data = request.json
    other_user_id = data.get("other_user_id")
    other_user = await request.app.db.users.find_account(**{'_id': other_user_id})
    await user.push_to_field('following', other_user.id)
    await other_user.push_to_field('followers', user.id)
    resp = {
        'success': True,
    }
    return response.json(resp)


@api.post("/unfollow")
@authrequired
@jsonrequired
async def unfollow(request, user):
    """
    Unfollows user
    Jason Yu
    """
    data = request.json
    other_user_id = data.get("other_user_id")
    other_user = await request.app.db.users.find_account(**{'_id': other_user_id})
    await user.remove_from_array_field('following', other_user.id)
    await user.remove_from_array_field('followers', user.id)
    resp = {
        'success': True,
    }
    return response.json(resp)

@api.post('/update_profile')
@authrequired
@jsonrequired
async def update_profile(request, user):
    """
    Updates user profile with args
    Jason Yu
    """
    data      = request.json
    password  = data.get('password')
    username  = data.get('username')
    full_name = data.get('full_name')
    bio       = data.get('bio')
    if bio is not None: 
        await user.set_field('bio', bio)
    if username is not None: 
        await user.set_field('username', username)
    if full_name is not None: 
        await user.set_field('full_name', full_name)
    if password is not None: 
        salt = bcrypt.gensalt()
        await user.set_to_dict_field('credentials', 'password', salt)
    resp = {
        'success': True,
    }
    return response.json(resp)


"""
Account Info API Calls
"""


@api.post("/get_info")
@authrequired
async def get_info(request, user):
    """
    Get user info
    Jason Yu/Sunny Yan
    """
    info = user.to_dict()
    resp = {
        'success': True,
        'info' : {
            'full_name': info['full_name'],
            'email': info['credentials']['email'],
            'username': info['username'],
            'points': info['stats']['points'],
            'followers': info['followers'],
            'following': info['following'],
            'stats': info['stats'],
            'bio': info['bio'],
        }
    }
    return response.json(resp)


@api.post("/find_friends")
@authrequired
@jsonrequired
async def find_friends(request, user):
    text = request.json['name']
    query = {"$text":  {"$search": text}}

    projection = {"_id": 1, "username": 1, "bio": 1}

    results = await request.app.db.users.find(query).to_list(10)
    results = [
        {"user_id": user["_id"], "name": user["username"], "bio": user["bio"]}
        for user in results
    ]

    return response.json(results)


@api.post("/get_saved_routes")
@authrequired
@jsonrequired
async def get_saved_routes(request, user):
    """
    Gets saved routes of user
    Jason Yu
    """
    saved_routes_json = [saved_route.to_dict() for saved_route in user.saved_routes]
    resp = {"success": True, "saved_routes_json": saved_routes_json}
    return response.json(resp)


@api.post("/get_recent_routes")
@authrequired
@jsonrequired
async def get_recent_routes(request, user):
    """
    Gets recent routes of user
    Jason Yu
    """
    recent_routes = [recent_route.to_dict() for recent_route in user.recent_routes]
    resp = {"success": True, "recent_routes": recent_routes}
    return response.json(resp)


@api.post("/get_run_info")
@authrequired
@jsonrequired
async def get_run_info(request, user):
    """
    Gets pace of user
    Jason Yu
    """
    data = request.json
    period = data.get("period", 5)
    speed = user.real_time_route.calculate_speed(period)
    pace = RealTimeRoute.speed_to_pace(speed)
    distance = user.real_time_route.current_distance
    resp = {"success": True, "pace": pace, "distance": distance}
    return response.json(resp)


@api.post('/get_feed')
@authrequired
@jsonrequired
async def get_feed(request, user):
    """
    Gets feed for user
    Returns 10 feed items
    Jason Yu
    """
    feed_items = [feed_item.to_dict() for feed_item in user.feed.get_latest_ten()]
    resp = {"success": True, "feed_items": feed_items}
    return response.json(resp)


"""
Group API Calls
"""


@api.post("/groups/create")
@authrequired
@jsonrequired
async def create_group(request, user):
    info = request.json
    await user.create_group(info)
    return response.json({"success": True})


@api.patch("/groups/<group_id>/edit")
@authrequired
@jsonrequired
async def edit_group(request, user, group_id):
    pass


@api.delete("/groups/<group_id>/delete")
@authrequired
async def delete_group(request, user, group_id):
    pass


@api.get("/groups/<group_id>/messages")
@authrequired
async def get_previous_messages(request, user, group_id):
    if not group_id == "global":
        abort(404)  # groups not implemented yet

    before = dateutil.parser.parse(request.args.get("before"))
    limit = 50

    query = {"group_id": group_id, "created_at": {"$lte": before}}

    cursor = request.app.db.messages.find(query).sort("created_at", -1)
    cursor.limit(limit)

    messages = []

    async for msg in cursor:
        msg["created_at"] = msg["created_at"].timestamp()
        messages.append(msg)

    return response.json(messages)


"""
Image API Calls
"""


@api.get("/route_images/<user_id>/<route_name>")
async def get_route_image(request, user_id, route_name):
    doc = await request.app.db.images.find_one(
        {"user_id": user_id, "route_name": route_name}
    )
    if not doc:
        abort(404)
    return response.raw(doc["route_image"], content_type="image/png")


@api.get("/avatars/<user_id>.png")
async def get_user_image(request, user_id):
    doc = await request.app.db.images.find_one({"user_id": user_id})
    if not doc:
        abort(404)
    return response.raw(doc["avatar"], content_type="image/png")


@api.patch("/avatars/update")
@authrequired
async def update_user_image(request, user):
    avatar = request.body
    await request.app.db.images.update_one(
        {"user_id": user.id}, {"$set": {"avatar": avatar}}
    )
    return response.json({"success": True})
