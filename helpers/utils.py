# oan/helpers/utils.py

import io
import math
import os
import re
from typing import List, Dict
import logging
import boto3
from dotenv import load_dotenv
import base64
import numpy as np
import pytz
import tiktoken
import unicodedata as ud
from datetime import datetime
import simplejson as json
from jinja2 import Environment, FileSystemLoader
import soundfile as sf

load_dotenv()


def get_s3_client():
    """Get S3 client."""
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_REGION'),
        endpoint_url=os.getenv("AWS_ENDPOINT_URL", None)
    )


def get_today_date_str() -> str:
    """Get today's date as a string in the format Monday, 23rd May 2025."""
    today = datetime.now()
    return today.strftime('%A, %d %B %Y')


def _start_day_of_ethiopian(year):
    """ returns first day of that Ethiopian year

    Params:
    * year: an int """

    # magic formula gives start of year
    new_year_day = (year // 100) - (year // 400) - 4

    # if the prev ethiopian year is a leap year, new-year occrus on 12th
    if (year - 1) % 4 == 3:
        new_year_day += 1

    return new_year_day

def to_ethiopian(year, month, date):
        """ Ethiopian date string representation of provided Gregorian date

        Params:
        * year: an int
        * month: an int
        * date: an int """

        # prevent incorect input
        inputs = (year, month, date)
        if 0 in inputs or [data.__class__ for data in inputs].count(int) != 3:
            raise ValueError("Malformed input can't be converted.")

        # date between 5 and 14 of May 1582 are invalid
        if month == 10 and date >= 5 and date <= 14 and year == 1582:
            raise ValueError("Invalid Date between 5-14 May 1582.")

        # Number of days in gregorian months
        # starting with January (index 1)
        # Index 0 is reserved for leap years switches.
        gregorian_months = [0, 31, 28, 31, 30, 31, 30, \
                            31, 31, 30, 31, 30, 31]

        # Number of days in ethiopian months
        # starting with January (index 1)
        # Index 0 is reserved for leap years switches.
        ethiopian_months = [0, 30, 30, 30, 30, 30, 30, 30, \
                            30, 30, 5, 30, 30, 30, 30]

        # if gregorian leap year, February has 29 days.
        if  (year % 4 == 0 and year % 100 != 0) or year % 400 == 0:
            gregorian_months[2] = 29

        # September sees 8y difference
        ethiopian_year = year - 8

        # if ethiopian leap year pagumain has 6 days
        if ethiopian_year % 4 == 3:
            ethiopian_months[10] = 6
        else:
            ethiopian_months[10] = 5

        # Ethiopian new year in Gregorian calendar
        new_year_day = _start_day_of_ethiopian(year - 8)

        # calculate number of days up to that date
        until = 0
        for i in range(1, month):
            until += gregorian_months[i]
        until += date

        # update tahissas (december) to match january 1st
        if ethiopian_year % 4 == 0:
            tahissas = 26
        else:
            tahissas = 25

        # take into account the 1582 change
        if year < 1582:
            ethiopian_months[1] = 0
            ethiopian_months[2] = tahissas
        elif until <= 277 and year == 1582:
            ethiopian_months[1] = 0
            ethiopian_months[2] = tahissas
        else:
            tahissas = new_year_day - 3
            ethiopian_months[1] = tahissas

        # calculate month and date incremently
        m = 0
        for m in range(1, ethiopian_months.__len__()):
            if until <= ethiopian_months[m]:
                if m == 1 or ethiopian_months[m] == 0:
                    ethiopian_date = until + (30 - tahissas)
                else:
                    ethiopian_date = until
                break
            else:
                until -= ethiopian_months[m]

        # if m > 4, we're already on next Ethiopian year
        if m > 10:
            ethiopian_year += 1

        # Ethiopian months ordered according to Gregorian
        order = [0, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 1, 2, 3, 4]
        ethiopian_month = order[m]

        return (ethiopian_year, ethiopian_month, ethiopian_date)


def get_ethiopian_date_str() -> str:
    """Get today's date in Ethiopian calendar format with Amharic month names.

    Uses the local to_ethiopian function for conversion.

    Returns:
        str: Date in format "ጥር 19, 2018"
    """
    # Amharic month names
    ethiopian_months = [
        "መስከረም",  # 1 - Meskerem
        "ጥቅምት",   # 2 - Tikimt
        "ኅዳር",    # 3 - Hidar
        "ታኅሣሥ",   # 4 - Tahsas
        "ጥር",     # 5 - Tir
        "የካቲት",   # 6 - Yekatit
        "መጋቢት",   # 7 - Megabit
        "ሚያዝያ",   # 8 - Miyazya
        "ግንቦት",   # 9 - Ginbot
        "ሰኔ",     # 10 - Sene
        "ሐምሌ",    # 11 - Hamle
        "ነሐሴ",    # 12 - Nehase
        "ጳጉሜ",    # 13 - Pagume
    ]

    today = datetime.now(pytz.timezone("Africa/Addis_Ababa"))
    eth_year, eth_month, eth_day = to_ethiopian(today.year, today.month, today.day)

    return f" {ethiopian_months[eth_month - 1]} {eth_day}/{eth_year}"


def get_logger(name) -> logging.Logger:
    """Get logger object."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger

def count_tokens_str(doc: str) -> int:
    """Count tokens in a string.

    Args:
        doc (str): String to count tokens for.
    Returns:
        int: number of tokens in the string

    """
    encoder = tiktoken.get_encoding('cl100k_base')
    return len(encoder.encode(doc, disallowed_special=()))


def count_tokens_for_part(part) -> int:
    """Count tokens for a message part, handling different part types appropriately.
    
    Args:
        part: A message part (TextPart, ToolCallPart, etc.)
    Returns:
        int: number of tokens in the part
    """
    if hasattr(part, 'content'):
        return count_tokens_str(str(part.content))
    elif hasattr(part, 'part_kind') and part.part_kind == 'tool-call':
        # For tool calls, create a string representation of the tool name and args
        tool_str = f"tool: {part.tool_name}, args: {json.dumps(part.args)}"
        return count_tokens_str(tool_str)
    elif hasattr(part, 'part_kind') and part.part_kind == 'tool-return':
        # For tool returns, use the result content
        return count_tokens_str(str(part.content))
    else:
        # For unknown part types, return 0 tokens
        return 0



def is_sentence_complete(text: str) -> bool:
    """Check if the text is a complete sentence.
    
    Args:
        text (str): Text to check.

    Returns:
        bool: True if the text is a complete sentence, False otherwise.
    """
    # Check if text ends with a sentence terminator (., !, ?) possibly followed by whitespace or newlines
    return text.endswith('\n')

def split_text(text: str) -> List[str]:
    """Split text into chunks based on newlines.
    
    Args:
        text (str): Text to split.

    Returns:
        list: List of chunks, split by newlines.
    """
    # Split on newlines and filter out empty strings
    chunks = [chunk + "\n" for chunk in text.split('\n')]
    return chunks


def remove_redundant_parenthetical(text: str) -> str:
    """
    Collapse "X (X)" → "X" for any Unicode text.

    * Works with Devanagari and other non-Latin scripts.
    * Keeps bullets, punctuation, spacing, etc. unchanged.
    * Normalises both copies of the term to NFC first so that
      visually-identical strings made of different code-point
      sequences (e.g., decomposed vowel signs) are still caught.
    """
    # Optional but helps when the same glyph can be encoded two ways
    text = ud.normalize("NFC", text)

    pattern = re.compile(
        r'''
        (?P<term>                 # 1st copy
            [^\s()]+              #   – at least one non-space, non-paren char
            (?:\s+[^\s()]+)*      #   – then zero-or-more <space + word>
        )
        \s*                       # spaces before '('
        \(\s*
        (?P=term)                 # identical 2nd copy
        \s*\)                     # closing ')'
        ''',
        flags=re.UNICODE | re.VERBOSE,
    )

    return pattern.sub(lambda m: m.group('term'), text)

def remove_redundant_angle_brackets(text: str) -> str:
    """
    Collapse "X <X>" → "X" for any Unicode text.

    * Works with Devanagari and other non-Latin scripts.
    * Keeps bullets, punctuation, spacing, etc. unchanged.
    * Normalises both copies of the term to NFC first so that
      visually-identical strings made of different code-point
      sequences (e.g., decomposed vowel signs) are still caught.
    """
    # Optional but helps when the same glyph can be encoded two ways
    text = ud.normalize("NFC", text)

    pattern = re.compile(
        r'''
        (?P<term>                 # 1st copy
            [^\s<>]+              #   – at least one non-space, non-angle-bracket char
            (?:\s+[^\s<>]+)*      #   – then zero-or-more <space + word>
        )
        \s*                       # spaces before '<'
        <\s*
        (?P=term)                 # identical 2nd copy
        \s*>                      # closing '>'
        ''',
        flags=re.UNICODE | re.VERBOSE,
    )

    return pattern.sub(lambda m: m.group('term'), text)

def post_process_translation(translation: str) -> str:
    """Post process translation.
    
    Args:
        translation (str): Translation to post process.

    Returns:
        str: Post processed translation.
    """
    # 1. Remove trailing `:` from text from each line
    lines = translation.split('\n')
    processed_lines = [line.rstrip(':') for line in lines]
    translation = '\n'.join(processed_lines)    
    # 2. Remove redundant parentheticals.
    translation = remove_redundant_parenthetical(translation)
    # 3. Remove redundant angle brackets.
    translation = remove_redundant_angle_brackets(translation)
    # 4. Remove double `::`
    translation = re.sub(r'::', ':', translation)
    translation = translation.replace(':**:', ':**')
    return translation



def get_prompt(prompt_file: str, context: Dict = {}, prompt_dir: str = "assets/prompts") -> str:
    """Load a prompt from a file and format it with a context using Jinja2 templating.

    Args:
        prompt_file (str): Name of the prompt file.
        context (dict, optional): Context to format the prompt with. Defaults to {}.
        prompt_dir (str, optional): Path to the prompt directory. Defaults to 'assets/prompts'.

    Returns:
        str: prompt
    """
    # if extension is not .md, add it
    if not prompt_file.endswith(".md"):
        prompt_file += ".md"

    # Create Jinja2 environment
    env = Environment(
        loader=FileSystemLoader(prompt_dir),
        autoescape=False  # We don't want HTML escaping for our prompts
    )

    # Get the template
    template = env.get_template(prompt_file)

    # Render the template with the context
    prompt = template.render(**context) if context else template.render()
    
    return prompt

def upload_audio_to_s3(audio_base64: str, session_id: str, bucket_name: str = None) -> Dict:
    """Upload base64 encoded audio to S3.
    
    Args:
        audio_base64 (str): Base64 encoded audio content
        session_id (str): Session ID for the conversation
        bucket_name (str, optional): S3 bucket name. Defaults to env variable.
        
    Returns:
        dict: Dictionary containing upload details
    """
    try:
        if not bucket_name:
            bucket_name = os.getenv('AWS_S3_BUCKET')
            
        if not bucket_name:
            raise ValueError("S3 bucket name not provided")
            
        # Decode base64 content
        audio_content = base64.b64decode(audio_base64)
        
        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"audio/{session_id}/{timestamp}.wav"
        
        # Get S3 client and upload
        s3_client = get_s3_client()
        s3_client.put_object(
            Bucket=bucket_name,
            Key=filename,
            Body=audio_content,
            ContentType='audio/wav'
        )
        
        return {
            'status': 'success',
            'bucket': bucket_name,
            'key': filename,
            'session_id': session_id
        }
        
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Error uploading audio to S3: {str(e)}")
        raise
    
    
    
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two coordinates in kilometers."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def pcm_to_base64_wav(audio: np.ndarray, sr: int = 16000) -> str:
    buffer = io.BytesIO()
    sf.write(buffer, audio, sr, format="WAV", subtype="PCM_16")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")