import os
import re
import sys
import logging
from collections import deque

import emoji
import redis
import json_logging
from flask import Flask, render_template, jsonify
from slack import WebClient
from dotenv import load_dotenv
from flask_cors import CORS
from slack.errors import SlackApiError
from slackeventsapi import SlackEventAdapter
from flask_socketio import SocketIO
from redis_collections import Deque, Dict


load_dotenv(verbose=True)

DEBUG = os.getenv('DEBUG')
PORT = os.getenv('PORT')
REDIS_URL = os.getenv('REDIS_URL')
MAX_MESSAGES = int(os.getenv('MAX_MESSAGES', 10))
MIRROR_CHANNEL = os.getenv('MIRROR_CHANNEL')
SLACK_SIGNING_SECRET = os.getenv('SLACK_SIGNING_SECRET')

app = Flask('slackmirror')
app.logger.setLevel(os.getenv('LOG_LEVEL', 'DEBUG'))

if not DEBUG:
    json_logging.init_flask(enable_json=True)
    json_logging.init_request_instrument(app)

slack_client = WebClient(os.getenv('SLACK_BOT_TOKEN'))
slack_events_adapter = SlackEventAdapter(SLACK_SIGNING_SECRET, "/slack/events", server=app)
CORS(app)
logging.getLogger('flask_cors').level = logging.DEBUG

r = redis.Redis().from_url(REDIS_URL)
cache = Dict(key='cache', redis=r)
messages = Deque(key='messages', redis=r, maxlen=MAX_MESSAGES)

def replace_slack_tags(t):
    t = re.sub(r'<@([a-zA-Z0-9]+)>', replace_user_id_with_name, t)
    t = re.sub(r':([a-zA-Z0-9_-]+)(::[a-zA-Z0-9_-])?:', replace_coloncode_to_emoji, t)
    t = re.sub(r'<(https?://.+?)\|([^>]+?)>', rf'<a href="\1" target="_blank">\2</a>', t)
    t = re.sub(r'<(https?://.+?)>', rf'<a href="\1" target="_blank">\1</a>', t)
    t = re.sub('<#[a-zA-Z0-9]+\|([a-zA-Z0-9æøåÅÆØäöÄÖ\-_]+)>', r"#\1", t)
    t = re.sub(r'\n{3,}', "\n\n", t)

    return t

def replace_user_id_with_name(m):
    return '@'+id_to_obj('user', m.group(1))['name']

def replace_coloncode_to_emoji(m):
    return coloncode_to_emoji(m.group(1))


def id_to_obj(typ, _id):
    app.logger.debug(f'Looking up {typ} {_id}')
    typ_to_api = {
        'user': 'users',
        'channel': 'conversations'
    }

    obj = cache.get(f'{typ}%{_id}')
    if not obj:
        obj = slack_client.api_call(f'{typ_to_api[typ]}.info', params={typ:_id}).get(typ)
        app.logger.debug(f"Adding obj {_id} to cache as {obj.get('name')}")
        cache[f'{typ}%{_id}'] = obj

    return obj


def coloncode_to_emoji(coloncode):
    app.logger.debug(f'converting {coloncode} to emoji')
    e = cache.get(f'emoji%{coloncode}')
    if (e):
        app.logger.debug(f'Found emoji {e}')
        if (e[:8] == 'https://'):
            return f'<img class="emoji" src="{e}" title="{coloncode}">'
        
        if (e[:6] == 'alias:'):
            return coloncode_to_emoji(coloncode[6:])
        
        return e

    return f':{coloncode}:'


# Create an event listener for "reaction_added" events and print the emoji name
@slack_events_adapter.on("message")
def message(message):
    if message.get('event'):
        event = message.get('event')
        app.logger.debug(f'Event: {event}')
        try:
            event['channel'] = id_to_obj('channel', event['channel'])['name']
            if MIRROR_CHANNEL == event['channel'] and event.get('user'):
                user = id_to_obj('user', event['user'])
                msg = {
                    'user': user['profile']['display_name_normalized'],
                    'image_48': user['profile']['image_48'],
                    'text': replace_slack_tags(event['text']),
                    'ts': event['ts']
                }
                app.logger.info(msg)
                messages.append(msg)
                socketio.emit('msg', msg)
            else:
                app.logger.debug(f"Ignoring event: {event}")
        except SlackApiError as e:
            assert e.response["ok"] is False
            assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'
            app.logger.error(f"Failed due to {e.response['error']}")

@app.route('/debug')
def hello_world():
    return render_template('index.html', async_mode=socketio.async_mode)


@app.route('/log')
def send_log():
    return jsonify(list(messages))

if __name__ == '__main__':
    with app.test_request_context():
        app.logger.info('Loading emojis')
        for k, v in emoji.unicode_codes.UNICODE_EMOJI.items():
            k = k.replace(':', '')
            cache.setdefault(f'emoji%{k}', v)

        for k, v in slack_client.api_call('emoji.list').get('emoji').items():
            cache[f'emoji%{k}'] = v

        socketio = SocketIO(app, cors_allowed_origins="*")
        app.logger.info('Monitoring #' + MIRROR_CHANNEL)
        socketio.run(app, host='0.0.0.0', debug=DEBUG, port=PORT)
