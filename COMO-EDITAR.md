# Cómo agregar o quitar un gestor

Todo se hace en un solo archivo: `managers.yaml`. Lo editas en la página de GitHub; no necesitas instalar nada.

## Agregar un gestor

1. Pídele a Claude el **CIK** del gestor, que es su número en la SEC. Solo existe si la firma presenta 13F.
2. En GitHub abre `managers.yaml` y haz clic en el lápiz (Edit) arriba a la derecha.
3. Copia un bloque completo, desde `- id:` hasta la línea `why:`, y pégalo al final.
4. Cambia los datos:
   - `id`: el mismo que usa en letters.ezrasnotes.com, si está ahí (lo ves en la dirección, por ejemplo `/m/hayden.html` → `hayden`). Si no está, usa el nombre de la firma en minúsculas y con guiones.
   - `name`, `firm`, `cik`.
   - `letters: yes` si tiene página en el sitio de cartas. Así su línea "why" se toma de ese sitio y aparece "Read his letters →".
   - `why`: tu línea, entre comillas dobles. No hace falta si pusiste `letters: yes`.
5. Haz clic en **Commit changes**. En 2 o 3 minutos el sitio baja todos sus 13F y publica su página.

Si en Issues aparece un aviso con CUSIPs sin nombre, son acciones que el sitio todavía no reconoce. Pásale el aviso a Claude y él completa `data/securities.yaml`.

## Quitar un gestor

1. Abre `managers.yaml` y haz clic en el lápiz.
2. Borra su bloque completo, desde `- id:` hasta la línea `why:`.
3. **Commit changes**.

Su página deja de aparecer en el sitio. Sus 13F siguen guardados en `data/filings/`, así que si lo vuelves a agregar, regresa con todo su historial.

## Reglas para que no se rompa

- Respeta los espacios al inicio de cada línea, igual que en los demás bloques.
- Si el texto lleva dos puntos (:), ponlo entre comillas dobles.
- Si algo sale mal, GitHub abre un Issue y te llega un correo. Nada de lo publicado se borra.
