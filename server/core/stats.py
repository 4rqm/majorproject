from functools import wraps

from sanic import Blueprint, response
from sanic.exceptions import abort
import jwt




def authrequired(func):
    """
    Abdur Raqeeb
    """    
    @wraps(func)
    async def wrapper(request, *args, **kwargs):
        if not request['session'].get('logged_in'):
            return response.redirect('/login')
        token = request['session'].get('token')
        user_id = jwt.decode(token, request.app.secret)['sub']
        user = await request.app.users.find_account(_id=user_id)
        if user:
            return await func(request, user, *args, **kwargs)
        else:
            abort(401, "Invalid token")
    return wrapper

stats = Blueprint('stats')

@stats.get('/login')
async def login(request):
    return request.app.render_template('login')

@stats.post('/login')
async def post_login(request):
    '''Logs in a user using web sessions.'''
    
    data = request.form
    email = data['email'][0]
    password = data['password'][0]
    
    query = {'credentials.email': email}

    user = await request.app.users.find_account(**query)
    if user is None:
        print('User not found')
        abort(403, 'Credentials invalid.')
    elif user.check_password(password) == False:
        print('Invalid password')
        abort(403, 'Credentials invalid.')

    token = await request.app.users.issue_token(user)
    
    request['session']['logged_in'] = True
    request['session']['token'] = token
    
    return response.redirect('/stats')

@stats.get('/stats')
@authrequired
async def show_stats(request, user):
    return request.app.render_template('stats', stats=user.stats.to_dict(), user=user)

    
    
  
  
