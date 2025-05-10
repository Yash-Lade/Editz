import streamlit as st
import ffmpeg
import tempfile
import os
import json
from groq import Groq
from PIL import Image, ImageDraw, ImageFont
from datetime import timedelta
import speech_recognition as sr
from pydub import AudioSegment

# Initialize Groq client
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
client = Groq(api_key=GROQ_API_KEY)

# Initialize speech recognizer
recognizer = sr.Recognizer()

# --- Core Functions ---

def get_trim_instructions(prompt):
    system_prompt = """You are a video editing assistant. Respond ONLY in valid JSON with these EXACT fields:
{"start_time": "number", "duration": "number"}
Rules:
1. Both values must be positive numbers
Example: 'trim first 5 seconds' -> {'start_time': '0', 'duration': '5'}
NO EXPLANATIONS, just the JSON."""
    
    try:
        chat_completion = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3
        )
        raw_response = chat_completion.choices[0].message.content.strip()
        edit_data = json.loads(raw_response)
        return {
            "start_time": float(edit_data["start_time"]),
            "duration": float(edit_data["duration"])
        }
    except Exception as e:
        st.error(f"Error getting trim instructions: {e}\nResponse: {raw_response}")
        return None

def get_text_overlay_instructions(prompt):
    system_prompt = """You are a video editing assistant. Respond ONLY in valid JSON with these EXACT fields:
{"text": "text", "start_time": "number", "duration": "number", 
"font_size": "number", "font_color": "color", "x_position": "string", "y_position": "string"}
Rules:
1. Use basic colors (white, black, red, etc.)
2. Font size 20-72
Example: 'Add title at top center from 5-10s' -> 
{"text": "My Title", "start_time": "5", "duration": "5", 
"font_size": "48", "font_color": "white", "x_position": "(w-text_w)/2", "y_position": "50"}
NO EXPLANATIONS, just the JSON."""
    
    try:
        chat_completion = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3
        )
        raw_response = chat_completion.choices[0].message.content.strip()
        data = json.loads(raw_response)
        return {
            "text": data["text"],
            "start_time": float(data["start_time"]),
            "duration": float(data["duration"]),
            "font_size": int(data["font_size"]),
            "font_color": data["font_color"],
            "x_position": data["x_position"],
            "y_position": data["y_position"]
        }
    except Exception as e:
        st.error(f"Error getting text instructions: {e}")
        return None

# --- Audio/Subtitle Functions ---

def extract_audio(video_path):
    """Extract audio from video as WAV file"""
    audio_path = tempfile.NamedTemporaryFile(suffix='.wav', delete=False).name
    (
        ffmpeg
        .input(video_path)
        .output(audio_path, acodec='pcm_s16le', ac=1, ar='16k')
        .run(overwrite_output=True, quiet=True)
    )
    return audio_path

def transcribe_audio(audio_path):
    """Transcribe audio to text using speech recognition"""
    try:
        with sr.AudioFile(audio_path) as source:
            audio = recognizer.record(source)
            text = recognizer.recognize_google(audio)
            return text
    except Exception as e:
        st.error(f"Speech recognition error: {str(e)}")
        return None

def generate_subtitles(text, chunk_size=5):
    """Generate simple subtitles from transcribed text"""
    words = text.split()
    subtitles = []
    for i in range(0, len(words), chunk_size):
        chunk = ' '.join(words[i:i+chunk_size])
        start_time = i * 0.5  # Approximate timing (0.5s per word)
        end_time = start_time + (chunk_size * 0.5)
        
        # Format times as HH:MM:SS,ms
        start_str = str(timedelta(seconds=start_time)).split('.')[0] + ",000"
        end_str = str(timedelta(seconds=end_time)).split('.')[0] + ",000"
        
        subtitles.append(f"{len(subtitles)+1}\n{start_str} --> {end_str}\n{chunk}\n")
    
    return "\n".join(subtitles)

# --- Video Processing Functions ---

def trim_video(input_path, output_path, start_time, duration):
    try:
        (
            ffmpeg
            .input(input_path, ss=start_time)
            .output(output_path, t=duration, c="copy")
            .run(overwrite_output=True, quiet=True)
        )
        return True
    except ffmpeg.Error as e:
        st.error(f"Trim error: {e.stderr.decode() if e.stderr else str(e)}")
        return False

def add_text_to_video(input_path, output_path, text_params):
    """Ultra-robust text overlay function with multiple fallbacks"""
    try:
        # First try: Simple approach with default font
        try:
            (
                ffmpeg
                .input(input_path)
                .filter_('drawtext',
                        text=text_params["text"],
                        enable=f'between(t,{text_params["start_time"]},{text_params["start_time"] + text_params["duration"]})',
                        x=text_params["x_position"],
                        y=text_params["y_position"],
                        fontsize=text_params["font_size"],
                        fontcolor=text_params["font_color"])
                .output(output_path,
                       vcodec='libx264',
                       acodec='copy',
                       pix_fmt='yuv420p')
                .global_args('-hide_banner')
                .global_args('-loglevel', 'error')
                .run(overwrite_output=True)
            )
            return True
            
        except ffmpeg.Error as e:
            st.warning("Standard method failed, trying alternative approach...")
            
            # Second try: Use libass subtitle filter instead
            try:
                # Create temporary ASS subtitle file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.ass', delete=False) as sub_file:
                    sub_file.write(f"""
[Script Info]
ScriptType: v4.00+
PlayResX: 384
PlayResY: 288

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{text_params["font_size"]},&H00FFFFFF,&H000000FF,&H00000000,0,0,0,0,100,100,0,0,1,1,0,5,10,10,10,0

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:{text_params["start_time"]:02.1f},0:00:{text_params["start_time"] + text_params["duration"]:02.1f},Default,,0,0,0,,{text_params["text"]}
""")
                    sub_path = sub_file.name

                (
                    ffmpeg
                    .input(input_path)
                    .filter_('ass', filename=sub_path)
                    .output(output_path,
                           vcodec='libx264',
                           acodec='copy',
                           pix_fmt='yuv420p')
                    .global_args('-hide_banner')
                    .global_args('-loglevel', 'error')
                    .run(overwrite_output=True)
                )
                os.unlink(sub_path)
                return True
                
            except ffmpeg.Error as e:
                st.warning("ASS subtitle method failed, trying final fallback...")
                
                # Final try: Use images instead of text
                try:
                    # Create temporary image with text
                    from PIL import Image, ImageDraw, ImageFont
                    img = Image.new('RGBA', (400, 100), (0, 0, 0, 0))
                    try:
                        font = ImageFont.truetype("arial.ttf", text_params["font_size"])
                    except:
                        font = ImageFont.load_default()
                    
                    d = ImageDraw.Draw(img)
                    d.text((10, 10), text_params["text"], fill=text_params["font_color"], font=font)
                    
                    img_path = tempfile.NamedTemporaryFile(suffix='.png', delete=False).name
                    img.save(img_path)
                    
                    (
                        ffmpeg
                        .input(input_path)
                        .filter_('movie', filename=img_path, loop=0, shortest=1)
                        .overlay(ffmpeg.input(input_path), 
                                enable=f'between(t,{text_params["start_time"]},{text_params["start_time"] + text_params["duration"]})',
                                x=text_params["x_position"],
                                y=text_params["y_position"])
                        .output(output_path,
                               vcodec='libx264',
                               acodec='copy',
                               pix_fmt='yuv420p')
                        .global_args('-hide_banner')
                        .global_args('-loglevel', 'error')
                        .run(overwrite_output=True)
                    )
                    os.unlink(img_path)
                    return True
                    
                except Exception as img_e:
                    st.error(f"All text overlay methods failed. Last error: {str(img_e)}")
                    return False
                    
    except Exception as e:
        st.error(f"Unexpected error: {str(e)}")
        return False

def add_subtitles_to_video(input_path, output_path, srt_content):
    """Burn subtitles into video"""
    try:
        # Create temporary SRT file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False) as srt_file:
            srt_file.write(srt_content)
            srt_path = srt_file.name
        
        (
            ffmpeg
            .input(input_path)
            .filter_('subtitles', filename=srt_path)
            .output(output_path, vcodec='libx264', acodec='copy', pix_fmt='yuv420p')
            .run(overwrite_output=True, quiet=True)
        )
        os.unlink(srt_path)
        return True
    except ffmpeg.Error as e:
        st.error(f"Subtitle error: {e.stderr.decode() if e.stderr else str(e)}")
        if os.path.exists(srt_path):
            os.unlink(srt_path)
        return False

# --- Streamlit UI ---

st.title("🎬 AI Video Editor")
st.write("Trim videos, add text overlays, or generate automatic subtitles")

video_file = st.file_uploader("Upload Video", type=["mp4", "mov", "avi"])
if not video_file:
    st.stop()

# Save uploaded file
with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_video:
    tmp_video.write(video_file.read())
    video_path = tmp_video.name

st.video(video_path)

tab1, tab2, tab3 = st.tabs(["✂️ Trim", "🖋️ Text Overlay", "🔤 Auto-Subtitles"])

with tab1:
    st.subheader("Trim Video")
    trim_prompt = st.text_area("How should we trim? (e.g., 'Keep first 30 seconds')", key="trim_prompt")
    if st.button("Trim", key="trim_btn") and trim_prompt:
        with st.spinner("Processing trim..."):
            params = get_trim_instructions(trim_prompt)
            if params:
                output_path = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
                if trim_video(video_path, output_path, params["start_time"], params["duration"]):
                    st.success("Trim successful!")
                    st.video(output_path)
                    with open(output_path, 'rb') as f:
                        st.download_button("Download", f, "trimmed.mp4")
                    os.unlink(output_path)

with tab2:
    st.subheader("Add Text Overlay")
    text_prompt = st.text_area("Describe your text (e.g., 'Add \"Welcome\" at bottom center from 5-10s')", key="text_prompt")
    if st.button("Add Text", key="text_btn") and text_prompt:
        with st.spinner("Adding text..."):
            params = get_text_overlay_instructions(text_prompt)
            if params:
                output_path = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
                if add_text_to_video(video_path, output_path, params):
                    st.success("Text added!")
                    st.video(output_path)
                    with open(output_path, 'rb') as f:
                        st.download_button("Download", f, "with_text.mp4")
                    os.unlink(output_path)

with tab3:
    st.subheader("Generate Subtitles from Audio")
    if st.button("Generate Subtitles Automatically", key="sub_btn"):
        with st.spinner("Processing..."):
            # Step 1: Extract audio
            audio_path = extract_audio(video_path)
            
            # Step 2: Transcribe audio
            st.info("Transcribing audio...")
            transcription = transcribe_audio(audio_path)
            os.unlink(audio_path)
            
            if transcription:
                st.success("Transcription successful!")
                st.text_area("Transcription", transcription, height=150)
                
                # Step 3: Generate subtitles
                st.info("Generating subtitles...")
                subtitles = generate_subtitles(transcription)
                st.text_area("Generated Subtitles", subtitles, height=200)
                
                # Step 4: Add subtitles to video
                st.info("Adding subtitles to video...")
                output_path = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
                if add_subtitles_to_video(video_path, output_path, subtitles):
                    st.success("Subtitles added successfully!")
                    st.video(output_path)
                    
                    with open(output_path, 'rb') as f:
                        st.download_button(
                            "Download Subtitled Video",
                            f,
                            "subtitled_video.mp4",
                            "video/mp4"
                        )
                    
                    os.unlink(output_path)

# Cleanup
os.unlink(video_path)