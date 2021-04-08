echo off
rem If we double clicked in windows, make sure we're in the right spot
cd %~dp0
echo Installing pyinstaller if not installed
pip install pyinstaller
cd ..
echo Building using pyinstaller
pyinstaller main.py --onefile --name toggl2clockify
echo Built to dist, moving to bin folder
if not exist "bin" mkdir "bin"
move /y dist\toggl2clockify.exe bin\toggl2clockify.exe
echo all done, moving you back to builder directory
cd builder
