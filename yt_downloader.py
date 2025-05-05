import os
import sys
import tempfile
import shutil
import logging
import yt_dlp
from moviepy import VideoFileClip
from moviepy.video.fx.Crop import Crop
import telebot
from telebot import types
from telebot.util import content_type_media

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize bot with token
TOKEN = "7613212323:AAE8cSkRYgU13JDAdO4pKN1ZEellmiMaE-s"  # Replace with your actual token
bot = telebot.TeleBot(TOKEN)

# Dictionary to store user states
user_states = {}

# Define state constants
WAITING_FOR_URL = 1
WAITING_FOR_TRIM_CHOICE = 2
WAITING_FOR_START_TIME = 3
WAITING_FOR_END_TIME = 4
WAITING_FOR_RATIO = 5
PROCESSING = 6

# Clear yt-dlp cache to avoid 403 errors
def clear_cache():
    ydl = yt_dlp.YoutubeDL()
    ydl.cache.remove()
    logger.info("yt-dlp cache cleared")

# Download YouTube video
def download_youtube_video(url, output_dir):
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Construct output path
    output_path = os.path.join(output_dir, "youtube.mp4")
    
    ydl_opts = {
        # Force specific format to avoid opus audio
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'merge_output_format': 'mp4',
        'quiet': True,
        'noplaylist': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        },
        # No audio extraction, just metadata
        'postprocessors': [{
            'key': 'FFmpegMetadata',
            'add_metadata': True,
        }],
        # Force format to avoid WebM/Opus
        'prefer_ffmpeg': True,
        'keepvideo': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            logger.info(f"Downloaded: {output_path}")
            return output_path
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        return None

# Function to crop video to specified aspect ratio
def crop_to_aspect_ratio(clip, ratio_choice):
    # Map numeric choices to aspect ratios
    ratio_map = {
        "1": "1:1",    # Square
        "2": "16:9",   # Landscape
        "3": "9:16",   # Portrait
        "4": "4:3",    # Traditional TV
        "5": "21:9"    # Ultrawide
    }
    
    ratio_str = ratio_map.get(ratio_choice, "original")
    
    if ratio_str == "original":
        logger.info("Using original aspect ratio")
        return clip
    
    logger.info(f"Cropping to {ratio_str} aspect ratio")
    
    w, h = clip.size
    
    if ratio_str == "1:1":
        # Square crop
        size = min(w, h)
        x1 = (w - size) // 2
        y1 = (h - size) // 2
        crop = Crop(x1=x1, y1=y1, width=size, height=size)
        return crop.apply(clip)
    
    elif ratio_str == "16:9":
        target_ratio = 16 / 9
    elif ratio_str == "9:16":
        target_ratio = 9 / 16
    elif ratio_str == "4:3":
        target_ratio = 4 / 3
    elif ratio_str == "21:9":
        target_ratio = 21 / 9
    else:
        logger.warning("Invalid aspect ratio. Using original video.")
        return clip

    current_ratio = w / h
    if current_ratio > target_ratio:
        # Video is wider than target ratio
        new_width = int(h * target_ratio)
        x1 = (w - new_width) // 2
        crop = Crop(x1=x1, y1=0, width=new_width, height=h)
        return crop.apply(clip)
    else:
        # Video is taller than target ratio
        new_height = int(w / target_ratio)
        y1 = (h - new_height) // 2
        crop = Crop(x1=0, y1=y1, width=w, height=new_height)
        return crop.apply(clip)

# Function to process video
def process_video(user_id):
    user_data = user_states[user_id]
    
    # Create temp directory for this user
    temp_dir = tempfile.mkdtemp()
    user_data['temp_dir'] = temp_dir
    
    try:
        # Download video
        bot.send_message(user_id, "⬇️ Downloading video... This may take a while.")
        video_path = download_youtube_video(user_data['url'], temp_dir)
        
        if not video_path or not os.path.exists(video_path):
            bot.send_message(user_id, "❌ Failed to download video. Please try again later.")
            return
        
        # Process video
        bot.send_message(user_id, "✂️ Processing video...")
        
        with VideoFileClip(video_path) as clip:
            # Get video info
            duration = clip.duration
            
            # Apply trim if needed
            if user_data['trim_choice'] == '2':  # User chose to trim
                start_time = float(user_data['start_time'])
                end_time = float(user_data['end_time'])
                trimmed = clip.subclipped(start_time, end_time)
            else:
                trimmed = clip.copy()
            
            # Apply aspect ratio crop
            cropped = crop_to_aspect_ratio(trimmed, user_data['ratio'])
            
            # Save final video
            output_path = os.path.join(temp_dir, "output_video.mp4")
            cropped.write_videofile(
                output_path,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=os.path.join(temp_dir, "temp-audio.m4a"),
                remove_temp=True,
                threads=4,
                logger=None
            )
            
            # Check if file is too large for Telegram (50MB limit)
            file_size = os.path.getsize(output_path) / (1024 * 1024)  # Size in MB
            
            if file_size > 50:
                bot.send_message(
                    user_id, 
                    f"⚠️ The processed video is {file_size:.1f}MB, which exceeds Telegram's 50MB limit. "
                    "Please use a shorter clip or different settings."
                )
            else:
                # Send the video back to user
                with open(output_path, 'rb') as video_file:
                    bot.send_message(user_id, "✅ Your video is ready!")
                    bot.send_video(
                        user_id, 
                        video_file,
                        caption=f"Processed YouTube video - {user_data.get('title', 'YouTube Download')}"
                    )
        
    except Exception as e:
        logger.error(f"Error processing video: {e}")
        bot.send_message(user_id, f"❌ Error processing video: {str(e)}")
    finally:
        # Clean up
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Error cleaning up temp directory: {e}")

# Command handlers
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, 
        "👋 Welcome to the YouTube Video Processor Bot!\n\n"
        "I can help you download, trim, and crop YouTube videos.\n\n"
        "To get started, use the /download command."
    )

@bot.message_handler(commands=['download'])
def start_download(message):
    user_id = message.from_user.id
    
    # Reset user state
    user_states[user_id] = {'state': WAITING_FOR_URL}
    
    bot.reply_to(message, 
        "🔗 Please send me a YouTube video link."
    )

# Message handler
@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    text = message.text
    
    # Initialize user state if not exists
    if user_id not in user_states:
        user_states[user_id] = {'state': WAITING_FOR_URL}
    
    current_state = user_states[user_id]['state']
    
    # Handle different states
    if current_state == WAITING_FOR_URL:
        # Check if text is a YouTube URL
        if "youtube.com" in text or "youtu.be" in text:
            user_states[user_id]['url'] = text
            user_states[user_id]['state'] = WAITING_FOR_TRIM_CHOICE
            
            # Create trim choice keyboard
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add('1) Download entire video', '2) Trim video')
            
            bot.send_message(
                user_id, 
                "⏱️ Do you want to download the entire video or trim it?",
                reply_markup=markup
            )
        else:
            bot.send_message(user_id, "❌ That doesn't look like a YouTube URL. Please send a valid YouTube link.")
    
    elif current_state == WAITING_FOR_TRIM_CHOICE:
        if text.startswith('1)'):  # Download entire video
            user_states[user_id]['trim_choice'] = '1'
            user_states[user_id]['state'] = WAITING_FOR_RATIO
            
            # Create aspect ratio keyboard
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup
            markup.add('1) 1:1 (Square)', '2) 16:9 (Landscape)')
            markup.add('3) 9:16 (Portrait)', '4) 4:3 (Traditional)')
            markup.add('5) 21:9 (Ultrawide)', '6) Original ratio')
            
            bot.send_message(
                user_id, 
                "📏 Choose an aspect ratio for your video:",
                reply_markup=markup
            )
            
        elif text.startswith('2)'):  # Trim video
            user_states[user_id]['trim_choice'] = '2'
            user_states[user_id]['state'] = WAITING_FOR_START_TIME
            
            bot.send_message(
                user_id, 
                "⏲️ Enter the start time in seconds (e.g., 30 for 30 seconds):"
            )
        else:
            bot.send_message(user_id, "❌ Please select one of the provided options.")
    
    elif current_state == WAITING_FOR_START_TIME:
        try:
            start_time = float(text)
            if start_time < 0:
                bot.send_message(user_id, "❌ Start time can't be negative. Please enter a positive number.")
            else:
                user_states[user_id]['start_time'] = text
                user_states[user_id]['state'] = WAITING_FOR_END_TIME
                
                bot.send_message(
                    user_id, 
                    "⏲️ Enter the end time in seconds (e.g., 60 for 60 seconds):"
                )
        except ValueError:
            bot.send_message(user_id, "❌ Please enter a valid number for the start time.")
    
    elif current_state == WAITING_FOR_END_TIME:
        try:
            end_time = float(text)
            start_time = float(user_states[user_id]['start_time'])
            
            if end_time <= start_time:
                bot.send_message(user_id, "❌ End time must be greater than start time. Please enter a valid end time.")
            else:
                user_states[user_id]['end_time'] = text
                user_states[user_id]['state'] = WAITING_FOR_RATIO
                
                # Create aspect ratio keyboard
                markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
                markup.add('1) 1:1 (Square)', '2) 16:9 (Landscape)')
                markup.add('3) 9:16 (Portrait)', '4) 4:3 (Traditional)')
                markup.add('5) 21:9 (Ultrawide)', '6) Original ratio')
                
                bot.send_message(
                    user_id, 
                    "📏 Choose an aspect ratio for your video:",
                    reply_markup=markup
                )
        except ValueError:
            bot.send_message(user_id, "❌ Please enter a valid number for the end time.")
    
    elif current_state == WAITING_FOR_RATIO:
        if text.startswith(('1)', '2)', '3)', '4)', '5)', '6)')):
            ratio_choice = text[0]  # Extract the number
            user_states[user_id]['ratio'] = ratio_choice
            user_states[user_id]['state'] = PROCESSING
            
            # Remove keyboard
            markup = types.ReplyKeyboardRemove()
            bot.send_message(
                user_id, 
                "🎬 Starting video processing...",
                reply_markup=markup
            )
            
            # Start processing in a new thread
            import threading
            thread = threading.Thread(target=process_video, args=(user_id,))
            thread.start()
        else:
            bot.send_message(user_id, "❌ Please select one of the provided options.")

# Start the bot
def main():
    logger.info("Starting bot...")
    
    # Check if ffmpeg is installed
    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg is not installed or not in PATH")
        sys.exit(1)
    
    # Clear cache once at startup
    clear_cache()
    
    # Start polling
    bot.infinity_polling()

if __name__ == "__main__":
    main()