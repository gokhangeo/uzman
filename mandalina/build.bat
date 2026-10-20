@echo off
rem Mandalina.exe'yi tek dosya olarak derler. Cikti: dist\Mandalina.exe
rem Not: Ara dosyalar kisa bir yola yazilir; uzun yollarda PyInstaller ikon eklerken hata veriyor.
setlocal
cd /d "%~dp0"
set WORK=%TEMP%\mandalina-build
python -m pip install -r requirements.txt || goto :hata
python -c "import mandalina as m; m.app_icon(256).save(r'%WORK%-icon.ico', sizes=[(16,16),(32,32),(48,48),(256,256)])" || goto :hata
python -m PyInstaller --noconfirm --onefile --windowed --name Mandalina ^
  --icon "%WORK%-icon.ico" ^
  --hidden-import pystray._win32 --hidden-import win32clipboard --hidden-import pymupdf ^
  --collect-all pillow_heif --collect-all pdf2docx ^
  --distpath dist --workpath "%WORK%" --specpath "%WORK%" mandalina.py || goto :hata
echo.
echo Hazir: %~dp0dist\Mandalina.exe
exit /b 0
:hata
echo Derleme basarisiz.
exit /b 1
