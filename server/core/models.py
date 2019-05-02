from dataclasses import dataclass
import datetime

import bcrypt
import jwt

from sanic import Sanic
from sanic.exceptions import abort

from .utils import snowflake

from .route import Route 

@dataclass
class Credentials:
    """
    Class to hold important user information
    Abdur Raqeeb
    """
    email: str
    password: str
    token: str = None

class Group:
    """
    A class that holds messages and information of members in a group
    Jason Yu
    """
    def __init__(self, app, data):
        self.app = app
        self.id = data['id']
        self.name = data['name']
        self.members = data['members']
        self.owner = data['owner']
        self.messages = []

    def invite_person(self, person):
        self.members.append(person)

    def invite_people(self,people):
        for person in people:
            self.invite_person(person)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "members": self.members,
            "owner": self.owner,
            "messages": self.messages
        }


class User:
    """
    User class for database that holds all information
    Abdur Raqeeb/Jason Yu
    """
    fields = ('id', 'credentials', 'routes')

    def __init__(self, app, user_id, credentials, full_name, dob, username, routes, groups, stats, real_time_route):
        self.app = app
        self.id = user_id
        self.credentials = credentials
        self.dob = dob
        self.username = username
        self.full_name = full_name
        self.routes = routes
        self.groups = groups
        self.stats = stats
        self.real_time_route = real_time_route

    def __hash__(self):
        return self.id

    @classmethod
    def from_data(cls, app, data):
        """
        Generates User class from database data
        Abdur Raqeeb
        """
        routes = data.pop('routes')
        data['user_id'] = str(data.pop('_id'))
        data['groups'] = [Group(app, g) for g in data.get('groups', [])]
        data['credentials'] = Credentials(*(data.pop('credentials')))
        data['stats'] = UserStats(*(data.pop('stats')))
        data['real_time_route'] = RealTimeRoute.from_data(*(data.pop('real_time_route')))
        user = cls(app, **data)
        user.routes = routes
        return user

    def check_password(self, password):
        """
        Checks encrypted password
        Abdur Raqeeb
        """
        return bcrypt.checkpw(password, self.credentials.password)

    async def update(self):
        """
        Updates user with current data
        Abdur Raqeeb
        """
        document = self.to_dict()
        await self.app.db.users.update_one({'user_id': self.id}, document)
    
    async def delete(self):
        """
        Deletes user from database
        Abdur Raqeeb
        """
        await self.app.db.users.delete_one({'user_id': self.id})
    
    async def create_group(self):
        return NotImplemented
    
    async def edit_group(self):
        return NotImplemented
    
    async def delete_group(self):
        return NotImplemented
    
    def to_dict(self):
        """
        Returns user data as a dict
        Abdur Raqeeb/ Jason Yu
        """
        return {
            "user_id": self.id,
            "routes": self.routes,
            "full_name": self.full_name,
            "username": self.username,
            "dob": self.dob,
            "avatar_url": None,
            "stats": {
                "num_runs": self.stats.num_runs,
                "total_distance": self.stats.total_distance,
                "longest_distance_ran": self.stats.longest_distance_ran,
                "fastest_km" : self.stats.fastest_km,
                "fastest_5km": self.stats.fastest_5km,
                "fastest_10km" : self.stats.fastest_10km,
                "fastest_marathon": self.stats.fastest_marathon,
                "estimated_v02_max": self.stats.estimated_v02_max,
                "average_heart_rate": self.stats.average_heart_rate,
                "cadence": self.stats.cadence,
            },
            "credentials": {
                "email": self.credentials.email,
                "password": self.credentials.password,
                "token": self.credentials.token,
            },
            "real_time_route" : {
                "location_history" : [{'location': location_packet.location,'time': location_packet.time} for location_packet in self.real_time_route.location_history],
                "update_freq": self.real_time_route.update_freq
            },
            "groups": self.groups,
        }

class RealTimeRoute: 
    """
    Class that contains information of a real time run
    Not sure currently whether to implement on javascript side or not
    Real time route might be to connect multiple people running same race
    Jason Yu
    """
    def __init__(self, update_freq, location_history):
        self.location_history = location_history
        self.update_freq = update_freq

    def update_location_history(self, location, time):
        self.location_history.append(LocationPacket(location,time))

    @staticmethod
    def get_distance(locations):
        return Route.get_route_distance(locations)

    def calculate_speed(self, period):
        """
        Speed for the last period of time
        Jason Yu
        """
        location_count = int(period / self.update_freq)
        if location_count < 2: 
            raise Exception("Period not long enough")
        else:
            history_length = len(self.location_history)
            locations = [location_packet.location for location_packet in self.location_history[(history_length-1)-location_count:]]
            total_distance = RealTimeRoute.get_distance(locations)
            speed = total_distance / period
            return speed

    def calculate_average_speed(self):
        """
        Speed for the whole duration of time
        Jason Yu
        """
        current_duration = (len(self.location_history) - 1) * self.update_freq #Total elapsed time
        locations = [location_packet.location for location_packet in self.location_history]
        total_distance = RealTimeRoute.get_distance(locations)
        speed = total_distance / current_duration
        return speed

    @staticmethod
    def calculate_pace(speed):
        """Speed is in m/s"""
        total_seconds = int(1000 / speed)
        minutes = int(total_seconds / 60)
        seconds = total_seconds - 60 * minutes
        return {"minutes": minutes, "seconds": seconds}

    @classmethod
    def from_data(cls, update_freq, location_history):
        location_history = [LocationPacket(location_packet.location, location_packet.time) for location_packet in location_history]
        real_time_route = cls(update_freq, location_history)
        return real_time_route

class LocationPacket:
    def __init__(self, location, time):
        self.location = location
        self.time = time

class RunningSession:
    """
    Running Session holds multiple people running the same race
    Coaches can view runners realtime data
    """
    def __init__(self, users):
        self.runners = dict((user.fullname, user) for user in users)

    def get_speeds(self, period):
        information = {}
        for user_name,user in self.runners.items(): 
            speed = user.running_session.calculate_speed(period)
            information[user_name] = speed
        return information

    def get_average_speeds(self):
        information = {}
        for user_name,user in self.runners.items(): 
            speed = user.running_session.calculate_average_speed()
            information[user_name] = speed
        return information

    def get_distances(self):
        information = {}
        for user_name,user in self.runners.items(): 
            locations = user.running_session.location_history
            distance = RealTimeRoute.get_distance(locations)
            information[user_name] = distance
        return information

@dataclass
class UserStats:
    """
    Class to hold user running stats
    Jason Yu
    """
    num_runs: int = 0
    total_distance: int = 0
    longest_distance_ran: int = None
    fastest_km : int = None
    fastest_5km: int = None
    fastest_10km : int = None
    fastest_marathon: int = None
    estimated_v02_max: int = None
    average_heart_rate: int = None
    cadence: int = None

class SavedRoute: 
    """
    A route that has been saved by the user to be shared on feed
    Jason Yu
    """
    def __init__(self, route, start_time, end_time, duration, points, description, route_image):
        self.distance = route.distance
        self.start_time = start_time
        self.end_time = end_time
        self.duration = duration
        self.points = points
        self.description = description
        self.route_image = route_image

        self.comments = []
        self.likes = 0

    def to_dict(self):
        return  {
            "distance": self.distance,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "points": self.points,
            "description": self.description,
            "route_image": self.route_image,
            "comments": self.comments,
            "likes": self.likes
        }

    def get_route_image(self):
        return self.route_image

class UserBase:
    def __init__(self, app):
        self.app = app
        self.user_cache = {}
        self.group_cache = {}
    
    async def find_account(self, **query):
        """
        Returns a user object based on the query
        Abdur Raqeeb
        """

        if len(query) == 1 and 'user_id' in query:
            user =  self.user_cache.get(query['user_id'])
            if user:
                return user

        data = await self.app.db.users.find_one(query)

        if not data: 
            return None
        
        user = User.from_data(self.app, data)
        self.user_cache[user.id] = user
        return user

    async def register(self, request):
        """
        Registers user to database
        Abdur Raqeeb
        """
        data = request.json

        email = data.get('email')
        password = data.get('password')
        full_name = data.get('full_name')
        dob = data.get('dob')
        username = data.get('username')
        query = {'credentials.email': email}
        exists = await self.find_account(**query)
        if exists: abort(403, 'Email already in use.') 

        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password, salt)

        document = {
            "routes": [],
            "full_name": full_name,
            "username": username,
            "dob": dob,
            "stats":  {               
                "num_runs": 0,
                "total_distance": 0,
                "longest_distance_ran": 0,
                "fastest_km" : None,
                "fastest_5km": None,
                "fastest_10km" : None,
                "fastest_marathon": None,
                "estimated_v02_max": None,
                "average_heart_rate": None,
                "cadence": None,
            },
            "credentials": {
                "email": email,
                "password": hashed,
                "token": None
            },
            "real_time_route" : {
                "location_history" : [],
                "update_freq": None,
            },
            "groups": [],
        }

        result = await self.app.db.users.insert_one(document)
        document['user_id'] = str(result.inserted_id)
        user = User.from_data(self.app, document)
        return user

    async def issue_token(self, user):
        '''
        Creates and returns a token if not already existing
        Abdur Raqeeb
        '''
        if user.credentials.token:
            return user.credentials.token

        payload = {
            'sub': user.id,
            'iat': datetime.datetime.utcnow()
        }

        user.credentials.token = token = jwt.encode(payload, self.app.secret)

        await self.app.db.users.update_one(
            {'user_id': user.id}, 
            {'$set': {'credentials.token': token}}
        )
        
        return token

class Overpass:
    """Sunny"""
    
    BASE = 'http://overpass-api.de/api/interpreter?data='
    REQ = BASE + '''
[out:json];
(
    way
        [highway]
        (poly:"{}");
    >;
);
out;'''.replace("\n","").replace("\t","")
    #^^Replace statements only required to make the command easier to read
    #You can put this command in one line in the final version
    #Command description: Finds all ways with the tag highway in the area given,
    #then finds all nodes associated with these ways

class Color:
    green = 0x2ecc71
    red = 0xe74c3c
    orange = 0xe67e22
