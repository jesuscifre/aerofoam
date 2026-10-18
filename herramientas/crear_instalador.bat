@echo off
rem Genera instalador\salida\AeroFoam_Setup_X.Y.exe
rem Necesita: pip install pyinstaller  e  Inno Setup 6 instalado.
cd /d "%~dp0.."

for /f %%v in ('python -c "import aerofoam; print(aerofoam.__version__)"') do set VERSION=%%v
echo === AeroFoam %VERSION% ===

echo.
echo [1/2] Empaquetando el programa con PyInstaller...
python -m PyInstaller --noconfirm --clean --log-level WARN --distpath instalador\dist --workpath instalador\build instalador\aerofoam.spec
if errorlevel 1 goto error

set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
echo.
echo [2/2] Creando el instalador con Inno Setup...
"%ISCC%" /Q /DVersion=%VERSION% instalador\aerofoam.iss
if errorlevel 1 goto error

echo.
echo Listo: instalador\salida\AeroFoam_Setup_%VERSION%.exe
pause
exit /b 0

:error
echo.
echo *** Ha fallado la creacion del instalador ***
pause
exit /b 1
