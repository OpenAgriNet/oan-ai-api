from __future__ import absolute_import, unicode_literals

import os
import sys
from decouple import config
from celery import Celery
from kombu import Queue, Exchange
from django.conf import settings
from dotenv import load_dotenv
load_dotenv()

import logging
from logging.handlers import RotatingFileHandler

# Extend Python path for discovering utility modules and task definitions
git_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(git_dir)

# --------------------------- Logging Configuration ---------------------------
logger = logging.getLogger('celery_tasks')
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler('celery_tasks.log', maxBytes=10 * 1024 * 1024, backupCount=1)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)
# --------------------------- Redis Configuration ---------------------------

REDIS_HOST = config('REDIS_HOST', 'localhost')
REDIS_PORT = config('REDIS_PORT', 6379)
REDIS_DB  = config('REDIS_DB', 0)

CELERY_BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
CELERY_RESULT_BACKEND = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'oan.settings')

app = Celery('oan',
             broker=CELERY_BROKER_URL,
             backend=CELERY_RESULT_BACKEND,
)
app.config_from_object('django.conf:settings')


# NOTE: Will use it to schedule any periodic tasks
CELERY_BEAT_SCHEDULE = {}


# Automatically discover tasks within a given list of modules when the Celery worker starts
app.autodiscover_tasks([
    'oan_app.tasks',
    'oan_app.tasks.suggestions',
    ]
)


app.conf.update(
    # Basic Task Settings
    task_default_queue='default',          
    task_default_exchange='default',       
    task_default_routing_key='task.default',  
    task_track_started=True,              
    task_time_limit=60*30,               # Reduced to 30 minutes - most tasks shouldn't take longer
    task_soft_time_limit=60*25,          # Reduced to 25 minutes - gives 5 min grace period
    task_serializer='json',              
    result_serializer='json',            
    accept_content=['json'],             
    timezone='Asia/Kolkata',             
    
    # Worker Behavior
    worker_prefetch_multiplier=4,        # Increased for better throughput on 8 cores
    task_acks_late=True,                
    worker_max_memory_per_child=1048576, # Increased to ~1GB per worker given 16GB RAM
    worker_send_task_events=True,        
    worker_max_tasks_per_child=200,      # Increased since we have more memory
    worker_lost_wait=20,
    
    # Broker (Redis) Connection Settings
    broker_pool_limit=None,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=10,
    broker_connection_retry=True,
    broker_connection_max_retries=5,
    broker_heartbeat=60,               # Reduced to 1 minute for faster failure detection
    broker_heartbeat_checkrate=2,      
    
    # Socket Settings
    broker_socket_timeout=5,
    broker_socket_connect_timeout=5,
    broker_socket_keepalive=True,
    broker_socket_keepalive_options={
        'timeout': 5,
        'keep_alive': 60,
    },
    
    # Advanced Broker Options
    broker_transport_options={
        'visibility_timeout': 60*30,    # Reduced to match task_time_limit
        'queue_order_strategy': 'priority',
        'sep': ':',
        'priority_steps': [0, 3, 6, 9],
        'socket_keepalive': True,
        'socket_timeout': 30,
    },
    
    # Result Backend Settings
    result_expires=60*60*24,           # Increased to 24 hours for better debugging
    result_backend_transport_options={
        'retry_on_timeout': True,
        'max_connections': 100,         # Increased pool size for 8 cores
        'socket_timeout': 5,
    },
    
    # Include Celery Beat Schedule
    beat_schedule=CELERY_BEAT_SCHEDULE,
)

# Set up Celery worker event listener for logging
@app.task(bind=True)
def debug_task(self):
    logger.info(f'Request: {self.request!r}')

if __name__ == '__main__':
    app.start()
