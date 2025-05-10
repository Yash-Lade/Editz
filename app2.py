import streamlit as st
import ffmpeg
import tempfile
import os
import json
from groq import Groq

# Set your GROQ API key
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "use your grok api key")
client = Groq(api_key=GROQ_API_KEY)

# Function to get trim instructions
def get_trim_instructions(prompt):
    system_prompt = (
        "You are a video editing assistant. Respond ONLY in valid JSON with these EXACT fields:\n"
        '{\n  "start_time": "number",\n  "duration": "number"\n}\n'
        "Rules:\n"
        "1. Both values must be positive numbers\n"
        "2. Example for 'trim first 5 seconds': \n"
        '{"start_time": "0", "duration": "5"}\n'
        "NO EXPLANATIONS, just the JSON."
    )
    
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
        
        # Convert and validate
        start = float(edit_data["start_time"])
        duration = float(edit_data["duration"])
        
        if duration <= 0:
            st.error("Duration must be greater than 0")
            return None
            
        return {"start_time": start, "duration": duration}
        
    except Exception as e:
        st.error(f"Error getting trim instructions: {e}\nResponse was: {raw_response}")
        return None

# Function to get text overlay instructions
def get_text_overlay_instructions(prompt):
    system_prompt = (
        "You are a video editing assistant. Respond ONLY in valid JSON with these EXACT fields:\n"
        '{\n'
        '  "text": "text to display",\n'
        '  "start_time": "number",\n'
        '  "duration": "number",\n'
        '  "font_size": "number",\n'
        '  "font_color": "color name or hex",\n'
        '  "x_position": "position or formula",\n'
        '  "y_position": "position or formula"\n'
        '}\n'
        "Rules:\n"
        "1. All time values in seconds\n"
        "2. Font size between 10-100\n"
        "3. Example for 'Add title My Video from 5s to 10s':\n"
        '{"text": "My Video", "start_time": "5", "duration": "5", '
        '"font_size": "48", "font_color": "white", "x_position": "(w-text_w)/2", "y_position": "100"}\n'
        "NO EXPLANATIONS, just the JSON."
    )
    
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
        return json.loads(raw_response)
        
    except Exception as e:
        st.error(f"Error getting text overlay instructions: {e}")
        return None

# Function to trim video
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
# Streamlit UI
st.title("🎬 AI-Powered Video Editor")

# File uploader
video_file = st.file_uploader("Upload your video", type=["mp4", "mov", "avi"])

if video_file:
    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_video:
        temp_video.write(video_file.read())
        temp_video_path = temp_video.name
    
    # Display original video
    st.video(temp_video_path)
    
    # Create tabs for different operations
    tab1, tab2 = st.tabs(["✂️ Trim Video", "🖋️ Add Text Overlay"])
    
    with tab1:
        st.subheader("Trim Video")
        trim_prompt = st.text_area(
            "Describe how you want to trim the video",
            placeholder="E.g., 'Trim the first 5 seconds' or 'Keep from 0:30 to 1:00'",
            key="trim_prompt"
        )
        
        if st.button("Trim Video", key="trim_button") and trim_prompt:
            with st.spinner("Trimming video..."):
                trim_params = get_trim_instructions(trim_prompt)
                
                if trim_params:
                    output_path = trim_video(
                        temp_video_path,
                        trim_params["start_time"],
                        trim_params["duration"]
                    )
                    
                    if output_path:
                        st.success("Trim successful!")
                        st.video(output_path)
                        
                        with open(output_path, "rb") as f:
                            st.download_button(
                                "📥 Download Trimmed Video",
                                f,
                                "trimmed_video.mp4",
                                "video/mp4",
                                key="trim_download"
                            )
                        
                        os.unlink(output_path)
    
    with tab2:
        st.subheader("Add Text Overlay")
        text_prompt = st.text_area(
            "Describe your text overlay",
            placeholder="E.g., 'Add title My Video from 5s to 10s in large white text at the top center'",
            key="text_prompt"
        )
        
        if st.button("Add Text", key="text_button") and text_prompt:
            with st.spinner("Adding text overlay..."):
                text_params = get_text_overlay_instructions(text_prompt)
                
                if text_params:
                    # Convert numeric values
                    text_params["start_time"] = float(text_params["start_time"])
                    text_params["duration"] = float(text_params["duration"])
                    text_params["font_size"] = int(text_params["font_size"])
                    
                    output_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
                    if add_text_to_video(temp_video_path, output_path, text_params):
                        st.success("Text added successfully!")
                        st.video(output_path)
                        
                        with open(output_path, "rb") as f:
                            st.download_button(
                                "📥 Download Video with Text",
                                f,
                                "video_with_text.mp4",
                                "video/mp4",
                                key="text_download"
                            )
                    
                    # Cleanup
                    if os.path.exists(output_path):
                        os.unlink(output_path)
    
    # Cleanup original file
    os.unlink(temp_video_path)
