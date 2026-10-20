@echo off
rem Mandalina.exe'yi tek dosya olarak derler. Cikti: dist\Mandalina.exe
rem Not: Ara dosyalar kisa bir yola yazilir; uzun yollarda PyInstaller ikon eklerken hata veriyor.
setlocal
cd /d "%~dp0"
set WORK=%TEMP%\mandalina-build
rem Surum: MANDALINA_VERSION (ornek "1.1" ya da etiket "mandalina-v1.1"); yoksa "dev".
rem "dev" derlemeler otomatik guncelleme yapmaz.
set VER=%MANDALINA_VERSION%
if "%VER%"=="" set VER=dev
set VER=%VER:mandalina-v=%
if not exist "%WORK%" mkdir "%WORK%"
> "%WORK%\version.txt" echo %VER%
echo Surum: %VER%
python -m pip install -r requirements.txt || goto :hata
python -c "import mandalina as m; m.app_icon(256).save(r'%WORK%-icon.ico', sizes=[(16,16),(32,32),(48,48),(256,256)])" || goto :hata
python -m PyInstaller --noconfirm --onefile --windowed --name Mandalina ^
  --icon "%WORK%-icon.ico" --add-data "%WORK%\version.txt;." ^
  --hidden-import pystray._win32 --hidden-import win32clipboard --hidden-import pymupdf ^
  --collect-all pillow_heif --collect-all pdf2docx ^
  --distpath dist --workpath "%WORK%" --specpath "%WORK%" mandalina.py || goto :hata
echo.
echo Hazir: %~dp0dist\Mandalina.exe
exit /b 0
:hata
echo Derleme basarisiz.
exit /b 1
