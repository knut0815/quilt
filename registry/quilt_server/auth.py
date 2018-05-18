import base64
from datetime import datetime, timedelta
import uuid

from flask import jsonify, request
from flask_json import as_json, jsonify
import itsdangerous
import json
import jwt
from passlib.context import CryptContext

from . import app, db
from .mail import send_email
from .models import Code, Token, User

CATALOG_URL = app.config['CATALOG_URL']

# TODO: better way to set secret key -- probably in config.py
app.secret_key = b'thirty two bytes for glory&honor'

DEFAULT_SENDER = 'support@quiltdata.io'

pwd_context = CryptContext(schemes=['pbkdf2_sha512'],
        pbkdf2_sha512__default_rounds=500000)
# Each round should take about half a second, 
# 500000 rounds experimentally determined

def generate_uuid():
    return str(uuid.uuid4())

def get_user(username):
    return (
            db.session.query(
                User
            ).filter(User.name==username)
            .one_or_none()
        )

def get_user_by_id(user_id):
    user = (
        db.session.query(
            User
        )
        .filter(User.id==user_id)
        .one_or_none()
    )
    return user

def set_unusable_password(username):
    user = get_user(username)
    user.password = ''
    db.session.add(user)
    db.session.commit()
    return True


def hash_password(password):
    return pwd_context.hash(password)

def send_activation_email(user):
    base = request.host_url
    link = '{base}activate/{link}'.format(base=base, link=generate_activation_link(user.id))
    body = (
        '<head><title></title></head>'
        '<body>'
        '<p>You recently signed up for Quilt.</p>'
        '<p>To activate your account, <a href="{link}">click here in the next 24 hours.</a></p>'
        '<p>Sincerely, <a href="https://quiltdata.com">Quilt Data</a></p>'
        '</body>'
    ).format(link=link)
    send_email(user.email, DEFAULT_SENDER, 'Activate your Quilt account', body)

@app.route('/activate/<link>')
def activate_endpoint(link):
    payload = verify_activation_link(link)
    if payload:
        _activate_user(payload['id'])
        return redirect("{CATALOG_URL}/login".format(CATALOG_URL=CATALOG_URL), code=302)
    else:
        response = jsonify({error: "Account activation failed."})
        response.status_code = 400
        return response

@app.route('/reset_password/<link>', methods=['POST'])
@as_json
def reset_password_endpoint(link):
    payload = verify_reset_link(link)
    if payload:
        data = request.get_json()
        password = data['password']
        user_id = payload['id']
        user = get_user_by_id(user_id)
        user.password = hash_password(password)
        db.session.add(user)
        db.session.commit()
        return {}
    else:
        return {'error': 'Password reset failed.'}, 400

@app.route('/register', methods=['POST'])
@as_json
def register_endpoint():
    data = request.get_json()
    username = data['username']
    password = data['password']
    email = data['email']
    try:
        _create_user(username, password=password, email=email)
        return {}
    except Exception as e:
        if str(e) == 'User already exists':
            return {'error': 'User already exists'}, 409 # 409 Conflict
        else:
            return {'error': 'Internal server error.'}, 500

def _create_user(username, password='', email=None, is_admin=False,
        first_name=None, last_name=None, force=False, requires_activation=True):
    existing_user = get_user(username)
    if requires_activation:
        is_active = False
    else:
        is_active = True
    if existing_user:
        if not force:
            raise Exception('User already exists')
        else:
            user = existing_user
            user.name = username
            user.password = hash_password(password)
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.is_active = is_active
            user.is_admin = is_admin
    else:
        user = User(
                id=generate_uuid(),
                name=username,
                password=hash_password(password),
                email=email,
                first_name=first_name,
                last_name=last_name,
                is_active=is_active,
                is_admin=is_admin)

    try:
        db.session.add(user)
        db.session.commit()
    except IntegrityError:
        raise Exception('User already exists')

    if requires_activation:
        send_activation_email(user)

def _activate_user(user_id):
    user = get_user_by_id(user_id)
    if user is None:
        raise Exception("User not found")
    user.is_active = True
    db.session.add(user)
    db.session.commit()

def get_code(user_id):
    code = (
        db.session.query(
            Code
        )
        .filter(Code.user_id == user_id)
        .one_or_none()
    )
    return code

def get_tokens(user_id):
    tokens = (
        db.session.query(
            Token
        )
        .filter(Token.user_id == user_id)
        .all()
    )
    return tokens

def update_last_login(user_id, timestamp=datetime.utcnow()):
    user = (
        db.session.query(
            User
        )
        .filter(User.id==user_id)
        .one_or_none()
    )
    if not user:
        raise Exception("User not found")

    user.last_login = timestamp
    db.session.add(user)
    db.session.commit()

def revoke_user_code_tokens(user_id):
    code = get_code(user_id)
    if code:
        db.session.delete(code)
    tokens = get_tokens(user_id)
    for token in tokens:
        db.session.delete(token)

def _delete_user(username):
    # TODO: revoke all tokens + code
    user = get_user(username)
    if user:
        db.session.delete(user)
    else:
        raise Exception("User to delete not found")
    revoke_user_code_tokens(user.id)
    db.session.commit()
    return user

def _enable_user(username):
    user = get_user(username)
    if user:
        user.is_active = True
        db.session.add(user)
        db.session.commit()
        return True
    else:
        raise Exception("User to enable not found")

def _disable_user(username):
    user = get_user(username)
    if user:
        user.is_active = False
        db.session.add(user)
        revoke_user_code_tokens(user.id)
        db.session.commit()
        return True
    else:
        raise Exception("User to disable not found")

def _list_users():
    users = db.session.query(User).all()
    return users

def issue_code(username):
    user_id = get_user(username).id
    code = (
        db.session.query(
            Code
        ).filter(Code.user_id==user_id)
        .one_or_none()
    )
    if code:
        code.code = generate_uuid()
    else:
        code = Code(user_id=user_id, code=generate_uuid())
    db.session.add(code)
    db.session.commit()
    return {'id': user_id, 'code': code.code}

def encode_code(code):
    return base64.b64encode(bytes(json.dumps({'id': code['id'], 'code': code['code']}), 'utf-8'))

def decode_code(code_str):
    return json.loads(base64.b64decode(code_str))

def decode_token(token_str):
    token = jwt.decode(token_str, app.secret_key, algorithm='HS256')
    return token

def check_token(user_id, token_id):
    token = (
        db.session.query(
            Token
        )
        .filter(Token.user_id==user_id)
        .filter(Token.token==token_id)
        .one_or_none()
    )
    return token is not None

def _verify(payload):
    user_id = payload['id']
    uuid = payload['uuid']
    user = get_user_by_id(user_id)
    if user is None:
        raise Exception('User ID invalid')

    if not check_token(user_id, uuid):
        raise Exception('Token invalid')
    return user

def verify_token_string(s):
    try:
        token = decode_token(s)
        user = _verify(token)
        return user
    except:
        return False

def exp_from_token(s):
    token = decode_token(s)
    return token['exp']

def revoke_token_string(token_str):
    token = decode_token(token_str)
    user_id = token['id']
    uuid = token['uuid']
    return revoke_token(user_id, uuid)

def revoke_token(user_id, token):
    t = (
        db.session.query(
            Token
        )
        .filter(Token.user_id==user_id)
        .filter(Token.token==token)
        .one_or_none()
    )
    if t is None:
        return False
    db.session.delete(t)
    db.session.commit()
    return True

def revoke_tokens(user_id):
    tokens = (
        db.session.query(
            Token
        ).filter(Token.user_id==user_id)
        .all()
    )
    for token in tokens:
        db.session.delete(token)
    db.session.commit()

def get_exp(mins=30):
    return datetime.utcnow() + timedelta(minutes=mins)

def issue_token(username, exp=None):
    user_id = get_user(username).id
    return issue_token_by_id(user_id, exp)

def issue_token_by_id(user_id, exp=None):
    uuid = generate_uuid()
    token = Token(user_id=user_id, token=uuid)
    db.session.add(token)
    db.session.commit()
    # TODO: store expiration time in database?

    exp = exp or get_exp()
    payload = {'id': user_id, 'uuid': uuid, 'exp': exp}
    token = jwt.encode(payload, app.secret_key, algorithm='HS256')
    return token.decode('utf-8')

def consume_code_string(code_str):
    code = decode_code(code_str)
    return consume_code(code['id'], code['code'])

def consume_code(user_id, code):
    code = (
        db.session.query(
            Code
        )
        .filter(Code.user_id==user_id)
        .filter(Code.code==code)
        .one_or_none()
    )
    if code is None:
        return False

    db.session.delete(code)
    db.session.commit()
    return user_id

def verify_hash(password, pw_hash):
    try:
        if not pwd_context.verify(password, pw_hash):
            raise Exception('Password verification failed')
    except ValueError:
        raise Exception('Password verification failed')
    return True

def try_login(username, password):
    result = (
        db.session.query(
            User.name,
            User.password,
            User.is_active
        ).filter(User.name==username)
        .one_or_none()
    )
    if not result:
        return False

    if not result.is_active:
        return False

    try:
        verify_hash(password, result.password)
    except Exception as e:
        return False
    return True

# TODO: change this to envvar-based solution
admin_username = 'calvin'
admin_password = 'beans'

def create_admin():
    # TODO: make sure this doesn't run in prod
    _create_user(admin_username, password=admin_password, force=True)
    user = get_user(admin_username)
    _activate_user(user.id)

# app.before_first_request(create_admin)

# TODO: lots of user management stuff
# TODO: build + test account creation
    # document how it currently works
    # make sure it's extensible to stuff like github auth
    # think about design for tables for third-party auth
# TODO: check CSRF token on login?
# TODO: move ApiException and friends to a new file and use them in this one
# TODO: test code + tokens revoked on disable/delete

@app.route('/beans/test')
@as_json
def beans_test():
    return {'host': request.host_url}


linkgenerator = itsdangerous.URLSafeTimedSerializer(
        app.secret_key,
        salt='quilt'
        )

ACTIVATE_SALT = 'activate'
PASSWORD_RESET_SALT = 'reset'
MAX_LINK_AGE = 60 * 60 # 1 hour

def generate_activation_link(user_id):
    payload = {'id': user_id}
    return linkgenerator.dumps(payload, salt=ACTIVATE_SALT)

def generate_reset_link(user_id):
    payload = {'id': user_id}
    return linkgenerator.dumps(payload, salt=PASSWORD_RESET_SALT)

def verify_activation_link(link, max_age=None):
    max_age = max_age if max_age is not None else MAX_LINK_AGE
    try:
        return linkgenerator.loads(link, max_age=max_age, salt=ACTIVATE_SALT)
    except:
        return False

def verify_reset_link(link, max_age=None):
    max_age = max_age if max_age is not None else MAX_LINK_AGE
    try:
        return linkgenerator.loads(link, max_age=max_age, salt=PASSWORD_RESET_SALT)
    except:
        return False

def reset_password(username):
    user = get_user(username)
    if not user:
        return False
    set_unusable_password(username)
    # TODO: send email
    link = generate_reset_link(user.id)
    return True