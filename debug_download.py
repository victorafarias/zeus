
import asyncio
import os
import sys

# Mock logger
class Logger:
    def info(self, msg, **kwargs):
        print(f"[INFO] {msg} {kwargs}")
    def error(self, msg, **kwargs):
        print(f"[ERROR] {msg} {kwargs}")

logger = Logger()

async def download_audio_with_ytdlp(url: str, output_dir: str, filename_base: str, cookies_path: str = None) -> str:
    # Nome base limpo
    filename_base = filename_base.replace(".mp3", "").replace(".mp4", "")
    nome_final_mp3 = f"{filename_base}.mp3"
    caminho_completo_saida = os.path.join(output_dir, nome_final_mp3)
    
    if os.path.exists(caminho_completo_saida):
        logger.info(f"Arquivo de áudio já existe: {caminho_completo_saida}")
        return caminho_completo_saida

    logger.info(f"Iniciando download ÁUDIO yt-dlp: {filename_base}")

    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        raise ImportError("yt-dlp não instalado")

    ydl_opts = {
        'outtmpl': os.path.join(output_dir, filename_base) + '.%(ext)s',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://cf-embed.play.hotmart.com/',
        },
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': False, # Change to False to see output
        'no_warnings': False,
        'nocheckcertificate': True,
        'verbose': True
    }

    if cookies_path:
        ydl_opts['cookiefile'] = cookies_path

    # Run in thread not strictly necessary for this script but keeping structure
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    if os.path.exists(caminho_completo_saida):
        return caminho_completo_saida
        
    return caminho_completo_saida

async def main():
    url = "https://vod-akm.play.hotmart.com/video/4Rzm53dVZV/hls/master-pkg-t-1749008747000.m3u8?hdnts=st%3D1766424331%7Eexp%3D1766424831%7Ehmac%3D70028e5b032c0e5e326ce10742cc68aac9f5914ef70d5903ee5dc57188a25f46&app=e852b342-70b7-467b-8688-4a9cf3c021dd"
    cookies_path = r"c:\Users\Administrator\zeus\debug_cookies.txt"
    output_dir = r"c:\Users\Administrator\zeus"
    
    print(f"Using cookies from: {cookies_path}")
    
    try:
        result = await download_audio_with_ytdlp(
            url=url,
            output_dir=output_dir,
            filename_base="Aula-3-Debug",
            cookies_path=cookies_path
        )
        print("Result:", result)
    except Exception as e:
        print("Error:", e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
