@echo off
REM Manuell, dynamisk historik-backfill via Open-Meteo + OpenAQ (alla providers) med interaktiv meny.

setlocal enabledelayedexpansion
set PROJECT_ROOT=%~dp0
set PYTHONPATH=%PROJECT_ROOT%

REM Om argument anges direkt, använd dem (för kommandorad)
if not "%~1"=="" (
    py "%PROJECT_ROOT%tools\backfill_history.py" %*
    pause
    exit /b
)

REM Interaktiv meny
:menu
cls
echo ========================================
echo   HISTORIK-BACKFILL - Välj alternativ
echo   (Open-Meteo + OpenAQ - alla providers)
echo ========================================
echo.
echo 1. Backfilla 30 dagar (alla städer, alla providers)
echo 2. Backfilla 90 dagar (alla städer, alla providers)
echo 3. Backfilla 180 dagar (alla städer, alla providers)
echo 4. Backfilla 365 dagar (alla städer, alla providers)
echo 5. Anpassat antal dagar (alla städer, alla providers)
echo 6. Backfilla specifik stad (anpassat antal dagar, alla providers)
echo 7. Bara väderdata (Open-Meteo, alla städer, 30 dagar)
echo 8. Bara pollutanter (OpenAQ, alla städer, 30 dagar)
echo 9. Avsluta
echo.
set /p choice="Välj alternativ (1-9): "

if "%choice%"=="1" (
    set DAYS=30
    set CITY_ARG=
    set PROVIDER=both
    goto run
)
if "%choice%"=="2" (
    set DAYS=90
    set CITY_ARG=
    set PROVIDER=both
    goto run
)
if "%choice%"=="3" (
    set DAYS=180
    set CITY_ARG=
    set PROVIDER=both
    goto run
)
if "%choice%"=="4" (
    set DAYS=365
    set CITY_ARG=
    set PROVIDER=both
    goto run
)
if "%choice%"=="5" (
    echo.
    set /p DAYS="Ange antal dagar: "
    if "!DAYS!"=="" (
        echo Ogiltigt antal dagar!
        pause
        goto menu
    )
    set CITY_ARG=
    set PROVIDER=both
    goto run
)
if "%choice%"=="6" (
    echo.
    set /p DAYS="Ange antal dagar: "
    if "!DAYS!"=="" (
        echo Ogiltigt antal dagar!
        pause
        goto menu
    )
    set /p CITY_ID="Ange city_id: "
    if "!CITY_ID!"=="" (
        echo Ogiltigt city_id!
        pause
        goto menu
    )
    set CITY_ARG=--city !CITY_ID!
    set PROVIDER=both
    goto run
)
if "%choice%"=="7" (
    set DAYS=30
    set CITY_ARG=
    set PROVIDER=openmeteo
    goto run
)
if "%choice%"=="8" (
    set DAYS=30
    set CITY_ARG=
    set PROVIDER=openaq
    goto run
)
if "%choice%"=="9" (
    exit /b
)

echo Ogiltigt val! Försök igen.
pause
goto menu

:run
cls
echo ========================================
echo   Kör backfill: --provider !PROVIDER! --days !DAYS! !CITY_ARG!
echo ========================================
echo.
if "!PROVIDER!"=="both" (
    echo Steg 1/2: Hämtar väderdata från Open-Meteo...
    echo.
    py "%PROJECT_ROOT%tools\backfill_history.py" --provider openmeteo --days !DAYS! !CITY_ARG!
    echo.
    echo ========================================
    echo Steg 2/2: Hämtar pollutanter från OpenAQ...
    echo ========================================
    echo.
    py "%PROJECT_ROOT%tools\backfill_history.py" --provider openaq --days !DAYS! !CITY_ARG!
) else (
    py "%PROJECT_ROOT%tools\backfill_history.py" --provider !PROVIDER! --days !DAYS! !CITY_ARG!
)
echo.
echo ========================================
echo   Backfill klar!
echo ========================================
pause
goto menu

