%% PROYECTO SISTEMAS DIGITALES - OSCILOSCOPIO Y MOTOR DE LINEALIZACIÓN EN TIEMPO REAL
% Tarjeta: STM32F407VG Discovery | Tasa de Muestreo: 250 Hz
% Sensor Fuerza: Tekscan FlexiForce A201-1 (0 a 4.4 N)
% Sensor Infrarrojo: Óptico de Proximidad (0 a 5.0 cm) con Filtro Dinámico de Luz Ambiente

clear; close all; clc;
try, delete(findall(0, 'Type', 'serialport')); catch, end
warning('off', 'all');

%% 1. Conexión Serial Automática con Tolerancia a Fallos
puertos = serialportlist("available");
modoSimulacion = false;
s = [];
baudRate = 115200;
Fs = 250; % Frecuencia de muestreo hardware TIM2 (Hz)
dt = 1 / Fs; % Periodo de muestreo exacto: 4.0 ms

if isempty(puertos)
    fprintf('\n[!] AVISO: No se detecto puerto COM fisico de la STM32.\n');
    fprintf('[*] Iniciando en MODO DEMO / SIMULACION DINAMICA A 250 Hz...\n\n');
    modoSimulacion = true;
else
    candidatos = ["COM14", "COM16", "COM13", "COM8", "COM7", "COM6", "COM5", "COM4", "COM3"];
    puerto = "";
    for c = candidatos
        if ismember(c, puertos)
            puerto = c;
            break;
        end
    end
    if puerto == ""
        puerto = puertos(end);
    end
    
    fprintf('[*] Conectando a STM32 Discovery en %s a %d baudios...\n', puerto, baudRate);
    try
        s = serialport(puerto, baudRate, "Timeout", 0.5);
        flush(s);
        fprintf('[+] ¡Conexion serie establecida con EXITO en %s a 250 Hz!\n\n', puerto);
    catch ME
        fprintf('[!] Error al abrir puerto %s: %s\n', puerto, ME.message);
        fprintf('[*] Activando MODO SIMULACION DINAMICA para no interrumpir el ensayo...\n\n');
        modoSimulacion = true;
    end
end

%% 2. Configuración de Interfaz Gráfica de 4 Cuadrantes
fig = figure('Name', 'Sistema de Control de Calidad y Ensamble 4.0 [FlexiForce 0-4.4N | IR 0-5.0cm]', ...
             'NumberTitle', 'off', 'Color', [0.07 0.09 0.12], ...
             'Position', [30 20 1260 790]);

global detenerMuestreo;
detenerMuestreo = false;

% Banner Superior Técnico
uicontrol('Style', 'text', ...
          'String', 'ESTACIÓN DE ENSAMBLE Y CONTROL DE CALIDAD 4.0   |   Posicionamiento IR [0 - 5.0 cm]   |   Prensado FlexiForce [0 - 4.4 N]', ...
          'Position', [15 754 1230 24], 'BackgroundColor', [0.13 0.17 0.23], ...
          'ForegroundColor', [0.75 0.85 0.95], 'FontWeight', 'bold', 'FontSize', 9.5);

% Dashboard Digital de Medición Superior
pnlMedidas = uipanel('Parent', fig, 'Position', [0.012 0.915 0.976 0.045], ...
                     'BackgroundColor', [0.11 0.14 0.19], 'BorderType', 'line', 'HighlightColor', [0.25 0.30 0.40]);

dispCH1 = uicontrol('Parent', pnlMedidas, 'Style', 'text', ...
                    'String', 'CH1 (FUERZA): 0.00 N (ADC: 0 | 0.00 V) | REPOSO', ...
                    'Units', 'normalized', 'Position', [0.01 0.05 0.38 0.88], ...
                    'BackgroundColor', [0.11 0.14 0.19], 'ForegroundColor', [1.0 0.60 0.1], ...
                    'FontWeight', 'bold', 'FontSize', 9.5, 'HorizontalAlignment', 'left');

dispCH2 = uicontrol('Parent', pnlMedidas, 'Style', 'text', ...
                    'String', 'CH2 (DISTANCIA): 5.0 cm (ADC: 218 | 0.18 V) | ESPERA PIEZA', ...
                    'Units', 'normalized', 'Position', [0.40 0.05 0.38 0.88], ...
                    'BackgroundColor', [0.11 0.14 0.19], 'ForegroundColor', [0.0 0.85 1.0], ...
                    'FontWeight', 'bold', 'FontSize', 9.5, 'HorizontalAlignment', 'left');

dispLOGIC = uicontrol('Parent', pnlMedidas, 'Style', 'text', ...
                      'String', 'ESTADO: EN ESPERA DE PIEZA | 250 Hz OK', ...
                      'Units', 'normalized', 'Position', [0.78 0.05 0.21 0.88], ...
                      'BackgroundColor', [0.11 0.14 0.19], 'ForegroundColor', [0.2 0.95 0.4], ...
                      'FontWeight', 'bold', 'FontSize', 9.5, 'HorizontalAlignment', 'center');

% Botón de Detener Inferior
uicontrol('Style', 'pushbutton', 'String', 'DETENER Y GUARDAR DATOS', ...
          'Position', [510 6 240 32], 'BackgroundColor', [0.82 0.18 0.18], ...
          'ForegroundColor', 'w', 'FontWeight', 'bold', 'FontSize', 10, ...
          'Callback', @(~,~) setDetener());

% =========================================================================
% CUADRANTE 1 (ARRIBA IZQUIERDA): CH1 - FUERZA DE PRENSADO / ENSAMBLE
% =========================================================================
ax1 = subplot(2, 2, 1);
grid(ax1, 'on'); grid(ax1, 'minor'); box(ax1, 'on'); hold(ax1, 'on');
ax1.Color = [0.03 0.04 0.06];
ax1.XColor = [0.7 0.75 0.8]; ax1.YColor = [1.0 0.60 0.1];
ax1.GridColor = [0.25 0.30 0.35]; ax1.MinorGridColor = [0.14 0.17 0.21];
ax1.GridAlpha = 0.6; ax1.MinorGridAlpha = 0.4;
xlabel(ax1, 'Tiempo [s]', 'FontWeight', 'bold', 'Color', [0.8 0.85 0.9]);
ylabel(ax1, 'Fuerza Prensado [N]', 'FontWeight', 'bold');
title(ax1, 'Cuadrante 1: CH1 Fuerza de Prensado / Ensamble (0 - 4.4 N)', 'FontSize', 10.5, 'FontWeight', 'bold', 'Color', [1.0 0.65 0.15]);
ylim(ax1, [-0.1 4.8]);
yticks(ax1, 0:0.5:4.4);
lineaFuerza = animatedline(ax1, 'Color', [1.0 0.55 0.0], 'LineWidth', 2.4);

% =========================================================================
% CUADRANTE 2 (ARRIBA DERECHA): CH2 - POSICIONAMIENTO Y PROXIMIDAD DE PIEZA
% =========================================================================
ax2 = subplot(2, 2, 2);
grid(ax2, 'on'); grid(ax2, 'minor'); box(ax2, 'on'); hold(ax2, 'on');
ax2.Color = [0.03 0.04 0.06];
ax2.XColor = [0.7 0.75 0.8]; ax2.YColor = [0.0 0.85 1.0];
ax2.GridColor = [0.25 0.30 0.35]; ax2.MinorGridColor = [0.14 0.17 0.21];
ax2.GridAlpha = 0.6; ax2.MinorGridAlpha = 0.4;
xlabel(ax2, 'Tiempo [s]', 'FontWeight', 'bold', 'Color', [0.8 0.85 0.9]);
ylabel(ax2, 'Posición / Distancia IR [cm]', 'FontWeight', 'bold');
title(ax2, 'Cuadrante 2: CH2 Posicionamiento de Pieza / Proximidad IR (0 - 5.0 cm)', 'FontSize', 10.5, 'FontWeight', 'bold', 'Color', [0.0 0.85 1.0]);
ylim(ax2, [-0.1 5.4]);
yticks(ax2, 0:1:5);
lineaDist = animatedline(ax2, 'Color', [0.0 0.85 1.0], 'LineWidth', 2.4);

% =========================================================================
% CUADRANTE 3 (ABAJO IZQUIERDA): MOTOR DE LINEALIZACIÓN EN VIVO (y = mx + b)
% =========================================================================
ax3 = subplot(2, 2, 3);
grid(ax3, 'on'); grid(ax3, 'minor'); box(ax3, 'on'); hold(ax3, 'on');
ax3.Color = [0.03 0.04 0.06];
ax3.XColor = [0.7 0.75 0.8]; ax3.YColor = [0.2 0.95 0.4];
ax3.GridColor = [0.25 0.30 0.35]; ax3.MinorGridColor = [0.14 0.17 0.21];
ax3.GridAlpha = 0.6; ax3.MinorGridAlpha = 0.4;
xlabel(ax3, 'Entrada Digital ADC [Cuentas 0 - 350]', 'FontWeight', 'bold', 'Color', [0.8 0.85 0.9]);
ylabel(ax3, 'Fuerza Linealizada [N]', 'FontWeight', 'bold');
title(ax3, 'Cuadrante 3: Curva de Linealizacion en Vivo [y = m*x + b]', 'FontSize', 10.5, 'FontWeight', 'bold', 'Color', [0.2 0.95 0.4]);
xlim(ax3, [0 350]);
ylim(ax3, [-0.1 4.8]);
yticks(ax3, 0:0.5:4.4);
xticks(ax3, 0:50:350);

% Recta Teórica de Calibración
adc_teorico = 65:10:365;
fuerza_teorica = min(4.4, (adc_teorico - 65) * (4.4 / 300.0));
plot(ax3, adc_teorico, fuerza_teorica, '--', 'Color', [0.4 0.55 0.7], 'LineWidth', 1.8);
text(ax3, 75, 4.2, 'F(ADC) = 0.01467*(ADC - 65)  (Rango Activo)', 'Color', [0.3 0.95 0.5], 'FontWeight', 'bold', 'FontSize', 9.5);

% Punto de Operación Dinámico en Tiempo Real (Perla Fósforo)
puntoOp = plot(ax3, 0, 0, 'o', 'MarkerSize', 12, 'MarkerFaceColor', [1.0 0.55 0.0], ...
               'MarkerEdgeColor', [1.0 1.0 1.0], 'LineWidth', 2);
trazaOp = animatedline(ax3, 'Color', [1.0 0.55 0.0], 'LineWidth', 1.5, 'MaximumNumPoints', 80);

% =========================================================================
% CUADRANTE 4 (ABAJO DERECHA): COMPARATIVA MULTIVARIABLE DEL PROCESO
% =========================================================================
axUni = subplot(2, 2, 4);
grid(axUni, 'on'); grid(axUni, 'minor'); box(axUni, 'on'); hold(axUni, 'on');
axUni.Color = [0.03 0.04 0.06];
axUni.GridColor = [0.25 0.30 0.35]; axUni.MinorGridColor = [0.14 0.17 0.21];
axUni.GridAlpha = 0.6; axUni.MinorGridAlpha = 0.4;
title(axUni, 'Cuadrante 4: Comparativa Multivariable del Ciclo (Fuerza vs Posicion)', 'FontSize', 10.5, 'FontWeight', 'bold', 'Color', [0.9 0.92 0.95]);
xlabel(axUni, 'Tiempo [s]', 'FontWeight', 'bold', 'Color', [0.8 0.85 0.9]);

yyaxis(axUni, 'left');
axUni.YColor = [1.0 0.55 0.0];
ylabel(axUni, 'Fuerza FlexiForce [N]', 'FontWeight', 'bold');
ylim(axUni, [-0.1 4.8]);
yticks(axUni, 0:1:4.4);
lineaUniF = animatedline(axUni, 'Color', [1.0 0.55 0.0], 'LineWidth', 2.2);

yyaxis(axUni, 'right');
axUni.YColor = [0.0 0.85 1.0];
ylabel(axUni, 'Distancia IR [cm]', 'FontWeight', 'bold');
ylim(axUni, [-0.1 5.4]);
yticks(axUni, 0:1:5);
lineaUniD = animatedline(axUni, 'Color', [0.0 0.85 1.0], 'LineWidth', 2.2);

%% 3. Bucle Principal de Adquisición a 250 Hz
tiempo = [];
fuerza_N = [];
voltaje_F = [];
adc_F = [];
dist_cm = [];
voltaje_IR = [];
adc_IR = [];
presencia_arr = [];

ventana = 1.4; % Ventana de 1.4 segundos de súper-zoom horizontal
bufBytes = uint8([]);

raw1_filt = 0.0;
raw2_filt = 218.0;

% Base adaptativa de luz ambiente para el Infrarrojo
baseIR = 218.0;

fprintf('[*] Adquiriendo en tiempo real a 250 Hz (FlexiForce 0-4.4N | IR 0-5.0cm)...\n');
tic;
tUltimaTrama = toc;

while ishandle(fig) && ~detenerMuestreo
    tActual = toc;
    hayDato = false;
    
    if ~modoSimulacion && ~isempty(s)
        % Watchdog de Comunicación Serial
        if (tActual - tUltimaTrama) > 1.2
            try
                delete(s);
                puertosAct = serialportlist("available");
                if ismember(puerto, puertosAct)
                    s = serialport(puerto, baudRate, "Timeout", 0.5);
                    flush(s);
                    tUltimaTrama = toc;
                    fprintf('[+] Puerto %s Reconectado Automaticamente!\n', puerto);
                end
            catch
            end
        end
        
        % Drenado para cero latencia
        try
            nDisp = s.NumBytesAvailable;
            if nDisp > 120
                read(s, nDisp - 75, "uint8");
            end
            if s.NumBytesAvailable > 0
                bufBytes = [bufBytes, read(s, s.NumBytesAvailable, "uint8")]; %#ok<AGROW>
            end
        catch
        end
        
        while length(bufBytes) >= 12
            idxA = find(bufBytes == 64, 1); % '@'
            if isempty(idxA)
                bufBytes = uint8([]);
                break;
            end
            if idxA > 1
                bufBytes = bufBytes(idxA:end);
                idxA = 1;
            end
            
            idxB = find(bufBytes == 59, 1); % ';'
            if isempty(idxB)
                if length(bufBytes) > 100, bufBytes = bufBytes(2:end); end
                break;
            end
            
            tramaChars = char(bufBytes(1:idxB));
            bufBytes = bufBytes(idxB+1 : end);
            
            nums = sscanf(tramaChars, '@,%d,%d,%d,%d,%d;');
            if length(nums) >= 4
                hayDato = true;
                tUltimaTrama = tActual;
                raw1_in = double(nums(3)); % CH1: FlexiForce (PA1)
                raw2_in = double(nums(4)); % CH2: Infrarrojo (PA4)
                break;
            end
        end
    else
        % MODO SIMULACIÓN DINÁMICA A 250 Hz (TOLERANCIA A FALLOS)
        hayDato = true;
        pause(0.004); % 4 ms = 250 Hz
        ciclo = mod(tActual, 4.0);
        if ciclo < 1.5
            % Fase 1: Pieza acercándose
            raw2_in = baseIR + (ciclo / 1.5) * 220.0 + randn()*3;
            raw1_in = 65.0 + randn()*1.5;
        elseif ciclo < 3.0
            % Fase 2: Prensado activo
            raw2_in = baseIR + 230.0 + randn()*2;
            progresoFuerza = (ciclo - 1.5) / 1.5;
            raw1_in = 65.0 + progresoFuerza * 220.0 + randn()*4;
        else
            % Fase 3: Retorno a reposo
            raw2_in = baseIR + (1.0 - (ciclo - 3.0)) * 200.0;
            raw1_in = 65.0 + randn()*1.5;
        end
    end
    
    if hayDato
        % =============================================================
        % CANAL 1: FUERZA FLEXIFORCE A201-1 (PA1) [0.0 a 4.4 N]
        % =============================================================
        if (raw1_in <= 65) || (raw1_in > 3800)
            raw1_filt = 0.0;
            fuerza = 0.00;
            volt1 = (raw1_in / 4095.0) * 3.3;
            esDesconectado1 = (raw1_in > 3800);
        else
            esDesconectado1 = false;
            raw1_filt = 0.85 * raw1_filt + 0.15 * raw1_in;
            volt1 = (raw1_filt / 4095.0) * 3.3;
            fuerza = min(4.40, max(0.00, (raw1_filt - 65.0) * (4.40 / 300.0)));
        end
        
        % =============================================================
        % CANAL 2: INFRARROJO DE PROXIMIDAD (PA4) [0.0 A 5.0 CM]
        % =============================================================
        if (raw2_in > 3800) || (raw2_in < 5)
            distancia = 5.0;
            volt2 = 0.02;
            raw2_filt = baseIR;
            esDesconectado2 = true;
        else
            esDesconectado2 = false;
            raw2_filt = 0.80 * raw2_filt + 0.20 * raw2_in;
            volt2 = (raw2_filt / 4095.0) * 3.3;
            delta = max(0, abs(raw2_filt - baseIR));
            
            if delta < 50.0
                distancia = 5.0;
                baseIR = 0.98 * baseIR + 0.02 * raw2_filt;
            else
                distancia = max(0.0, min(5.0, 5.0 - (delta - 50.0) * (5.0 / 250.0)));
            end
        end
        
        % Decisión Lógica
        esObjeto = double(distancia < 4.0);
        
        % Guardar datos
        tiempo(end+1) = tActual;             %#ok<SAGROW>
        fuerza_N(end+1) = fuerza;            %#ok<SAGROW>
        voltaje_F(end+1) = volt1;            %#ok<SAGROW>
        adc_F(end+1) = raw1_filt;            %#ok<SAGROW>
        dist_cm(end+1) = distancia;          %#ok<SAGROW>
        voltaje_IR(end+1) = volt2;           %#ok<SAGROW>
        adc_IR(end+1) = raw2_filt;           %#ok<SAGROW>
        presencia_arr(end+1) = esObjeto;     %#ok<SAGROW>
        
        % Graficar temporalmente en tiempo real
        addpoints(lineaFuerza, tActual, fuerza);
        addpoints(lineaDist, tActual, distancia);
        addpoints(lineaUniF, tActual, fuerza);
        addpoints(lineaUniD, tActual, distancia);
        
        set(puntoOp, 'XData', raw1_filt, 'YData', fuerza);
        addpoints(trazaOp, raw1_filt, fuerza);
        
        % Actualizar Dashboard Superior
        if esDesconectado1
            set(dispCH1, 'String', 'CH1 (FUERZA): [!] SENSOR DESCONECTADO (Pin PA1)', ...
                         'ForegroundColor', [1.0 0.4 0.0]);
        elseif fuerza >= 3.8
            set(dispCH1, 'String', sprintf('CH1 (FUERZA): %.2f N (ADC: %d | %.2fV) | SOBRECARGA', fuerza, round(raw1_filt), volt1), ...
                         'ForegroundColor', [1.0 0.3 0.3]);
        elseif fuerza <= 0.01
            set(dispCH1, 'String', sprintf('CH1 (FUERZA): 0.00 N (ADC: %d | %.2fV) | REPOSO', round(raw1_in), volt1), ...
                         'ForegroundColor', [0.75 0.75 0.75]);
        else
            set(dispCH1, 'String', sprintf('CH1 (FUERZA): %.2f N (ADC: %d | %.2fV) | PRESIONANDO', fuerza, round(raw1_filt), volt1), ...
                         'ForegroundColor', [1.0 0.60 0.1]);
        end
        
        if esDesconectado2
            set(dispCH2, 'String', 'CH2 (DISTANCIA): [!] SENSOR DESCONECTADO (Pin PA4)', ...
                         'ForegroundColor', [1.0 0.4 0.0]);
        elseif distancia >= 4.9
            set(dispCH2, 'String', sprintf('CH2 (POSICION): 5.0 cm (ADC: %d | %.2fV) | EN ESPERA', round(raw2_filt), volt2), ...
                         'ForegroundColor', [0.5 0.8 0.9]);
        elseif distancia <= 0.1
            set(dispCH2, 'String', sprintf('CH2 (POSICION): 0.0 cm (ADC: %d | %.2fV) | PIEZA EN CONTACTO', round(raw2_filt), volt2), ...
                         'ForegroundColor', [1.0 0.2 0.8]);
        else
            set(dispCH2, 'String', sprintf('CH2 (POSICION): %.1f cm (ADC: %d | %.2fV) | APROXIMANDO', distancia, round(raw2_filt), volt2), ...
                         'ForegroundColor', [0.0 0.85 1.0]);
        end
        
        % Lógica de Control de Calidad
        if esObjeto && (fuerza >= 1.0) && (fuerza <= 3.8)
            set(dispLOGIC, 'String', 'ENSAMBLE OPTIMO (CALIDAD OK)', ...
                           'ForegroundColor', [0.2 1.0 0.4]);
        elseif esObjeto && (fuerza > 3.8)
            set(dispLOGIC, 'String', '¡PIEZA APLASTADA / SOBREPRESION!', ...
                           'ForegroundColor', [1.0 0.2 0.2]);
        elseif esObjeto && (fuerza < 1.0)
            set(dispLOGIC, 'String', 'PIEZA EN POSICION (APLICAR FUERZA)', ...
                           'ForegroundColor', [1.0 0.9 0.2]);
        else
            set(dispLOGIC, 'String', 'EN ESPERA DE PIEZA | 250 Hz OK', ...
                           'ForegroundColor', [0.6 0.7 0.8]);
        end
        
        % Ventana deslizante horizontal de 1.4 segundos
        if tActual > ventana
            xlim(ax1, [tActual - ventana, tActual]);
            xlim(ax2, [tActual - ventana, tActual]);
            xlim(axUni, [tActual - ventana, tActual]);
        else
            xlim(ax1, [0, ventana]);
            xlim(ax2, [0, ventana]);
            xlim(axUni, [0, ventana]);
        end
        
        drawnow limitrate;
    end
end

%% 4. Cierre Seguro y Guardado Automático de Registros
if ~isempty(s)
    try delete(s); catch, end
end

if ~isempty(tiempo)
    duracion = tiempo(end) - tiempo(1);
    fsReal = 0;
    if length(tiempo) > 1, fsReal = 1 / mean(diff(tiempo)); end
    
    nombreMAT = 'datos_proyecto_sensores.mat';
    save(nombreMAT, 'tiempo', 'fuerza_N', 'voltaje_F', 'adc_F', ...
                    'dist_cm', 'voltaje_IR', 'adc_IR', 'presencia_arr');
    
    nombreCSV = 'datos_proyecto_sensores.csv';
    tabla = table(tiempo', adc_F', voltaje_F', fuerza_N', ...
                  adc_IR', voltaje_IR', dist_cm', presencia_arr', ...
                  'VariableNames', {'Tiempo_s', 'ADC_Fuerza', 'Voltaje_Fuerza_V', 'Fuerza_N', ...
                                    'ADC_IR', 'Voltaje_IR_V', 'Distancia_cm', 'Presencia_Logica_1_0'});
    writetable(tabla, nombreCSV);
    
    fprintf('\n=======================================================\n');
    fprintf('          REPORTE TECNICO FINAL DE ADQUISICION        \n');
    fprintf('=======================================================\n');
    fprintf('Archivo .mat guardado       : %s\n', nombreMAT);
    fprintf('Archivo Excel/CSV guardado  : %s\n', nombreCSV);
    fprintf('Muestras totales registradas: %d muestras\n', length(tiempo));
    fprintf('Tiempo total de prueba      : %.2f segundos\n', duracion);
    fprintf('Frecuencia de muestreo real : %.2f Hz\n', fsReal);
    fprintf('Fuerza maxima registrada    : %.2f N\n', max(fuerza_N));
    fprintf('Distancia maxima registrada : %.2f cm\n', max(dist_cm));
    fprintf('=======================================================\n\n');
    
    figRep = figure('Name', 'Reporte Formal de Adquisicion', ...
                    'Color', 'w', 'Position', [80 60 1050 680]);
    
    s1 = subplot(3, 1, 1);
    grid(s1, 'on'); grid(s1, 'minor'); box(s1, 'on'); hold(s1, 'on');
    plot(s1, tiempo, fuerza_N, 'Color', [0.85 0.30 0.05], 'LineWidth', 1.8);
    ylabel(s1, 'Fuerza Prensado [N]', 'FontWeight', 'bold');
    title(s1, 'Curva Temporal: Fuerza de Prensado e Insercion (Tekscan FlexiForce A201-1)', 'FontWeight', 'bold');
    ylim(s1, [-0.1 4.8]);
    
    s2 = subplot(3, 1, 2);
    grid(s2, 'on'); grid(s2, 'minor'); box(s2, 'on'); hold(s2, 'on');
    plot(s2, tiempo, dist_cm, 'Color', [0.00 0.45 0.80], 'LineWidth', 1.8);
    ylabel(s2, 'Posicion / Distancia [cm]', 'FontWeight', 'bold');
    title(s2, 'Curva Temporal: Posicionamiento y Proximidad de Pieza (Sensor IR)', 'FontWeight', 'bold');
    ylim(s2, [-0.1 5.4]);
    
    s3 = subplot(3, 1, 3);
    grid(s3, 'on'); grid(s3, 'minor'); box(s3, 'on'); hold(s3, 'on');
    title(s3, 'Comparativa Multivariable del Ciclo de Control de Calidad (Doble Eje Y)', 'FontWeight', 'bold');
    xlabel(s3, 'Tiempo [s]', 'FontWeight', 'bold');
    
    yyaxis(s3, 'left');
    plot(s3, tiempo, fuerza_N, 'Color', [0.85 0.30 0.05], 'LineWidth', 1.6);
    ylabel(s3, 'Fuerza FlexiForce [N]', 'FontWeight', 'bold');
    ylim(s3, [-0.1 4.8]);
    
    yyaxis(s3, 'right');
    plot(s3, tiempo, dist_cm, 'Color', [0.00 0.45 0.80], 'LineWidth', 1.6);
    ylabel(s3, 'Distancia IR [cm]', 'FontWeight', 'bold');
    ylim(s3, [-0.1 5.4]);
    
    saveas(figRep, 'reporte_graficas_sensores.png');
    disp('Grafica formal guardada exitosamente como "reporte_graficas_sensores.png"');
end

function setDetener()
    global detenerMuestreo;
    detenerMuestreo = true;
end
