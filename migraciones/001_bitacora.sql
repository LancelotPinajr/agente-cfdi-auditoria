-- Bitácora encadenada — migración para PostgreSQL (tarea 2.1)
--
-- La implementación que corre en las pruebas usa SQLite, para que el proyecto
-- se levante y se verifique sin instalar un servidor. Esta es la ruta de
-- producción; las propiedades que sostienen el sistema son las mismas y aquí
-- están anotadas una por una.

BEGIN;

-- ---------------------------------------------------------------------------
-- La cadena. Inmutable y eterna: aquí NO hay datos personales, solo hashes.
-- Por eso puede vivir para siempre sin chocar con el art. 11 de la LFPDPPP.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bitacora_cadena (
    inquilino     TEXT        NOT NULL,
    posicion      BIGINT      NOT NULL,
    hash_registro BYTEA       NOT NULL,
    hash_anterior BYTEA       NOT NULL,
    escrito_en    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (inquilino, posicion),
    -- Última línea de defensa contra una bifurcación: aunque fallara el
    -- candado, dos eslabones no pueden ocupar la misma posición.
    CONSTRAINT hash_de_32_bytes  CHECK (octet_length(hash_registro) = 32),
    CONSTRAINT previo_de_32_bytes CHECK (octet_length(hash_anterior) = 32)
);

-- ---------------------------------------------------------------------------
-- El contenido. Sí trae RFC y montos, así que SÍ caduca. Suprimir una fila de
-- aquí no rompe la cadena: los eslabones siguen enlazando y lo único que se
-- pierde es poder recalcular ese hash. Ver docs/contrato-expediente.md §5.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bitacora_registros (
    inquilino TEXT   NOT NULL,
    posicion  BIGINT NOT NULL,
    evento    TEXT   NOT NULL,
    canonico  BYTEA  NOT NULL,
    PRIMARY KEY (inquilino, posicion),
    FOREIGN KEY (inquilino, posicion)
        REFERENCES bitacora_cadena (inquilino, posicion) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- El registro de cesiones. La clave primaria es el UUID **a secas**.
--
-- Ahí vive la garantía contra la doble cesión: no es un SELECT antes del
-- INSERT —que tiene una carrera y es justo lo que explota quien manda las dos
-- solicitudes a la vez— sino una restricción que la base no puede violar.
--
-- El ámbito es global y no por inquilino a propósito: un folio fiscal lo emite
-- el SAT y pertenece a un solo emisor, así que acotarlo por inquilino lo
-- derrotaría cualquiera que pueda abrir dos cuentas.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cesiones (
    uuid        TEXT        PRIMARY KEY,
    inquilino   TEXT        NOT NULL,
    financiador TEXT        NOT NULL,
    posicion    BIGINT      NOT NULL,
    cedido_en   TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (inquilino, posicion)
        REFERENCES bitacora_cadena (inquilino, posicion)
);

CREATE INDEX IF NOT EXISTS idx_cadena_dia
    ON bitacora_cadena (inquilino, escrito_en);

-- ---------------------------------------------------------------------------
-- Append-only, impuesto por la base y no por la disciplina de quien escribe.
--
-- Un UPDATE o un DELETE sobre la cadena es siempre un error: si alguien los
-- necesita, lo que hace falta es un evento nuevo, no editar el pasado.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION bitacora_solo_anexa() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'bitacora_cadena es append-only: % rechazado en (%, %)',
        TG_OP, OLD.inquilino, OLD.posicion;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_bitacora_solo_anexa ON bitacora_cadena;
CREATE TRIGGER trg_bitacora_solo_anexa
    BEFORE UPDATE OR DELETE ON bitacora_cadena
    FOR EACH ROW EXECUTE FUNCTION bitacora_solo_anexa();

COMMIT;

-- ---------------------------------------------------------------------------
-- Cómo anexar (tarea 2.3): el candado consultivo
--
-- Leer la punta de la cadena y escribir el siguiente eslabón tienen que ser una
-- sola operación indivisible. Sin eso, dos escritores leen el mismo
-- hash_anterior y bifurcan.
--
--   BEGIN;
--     SELECT pg_advisory_xact_lock(hashtext(:inquilino));
--     -- ahora sí: leer punta, calcular hash, insertar
--   COMMIT;
--
-- `pg_advisory_xact_lock` se libera solo al terminar la transacción, así que no
-- hay forma de olvidarlo abierto. Es por inquilino: dos PYMEs distintas
-- escriben en paralelo sin estorbarse.
--
-- El candado evita el reintento; la clave primaria evita el desastre. Se
-- necesitan los dos: el candado es rendimiento, la restricción es corrección.
-- ---------------------------------------------------------------------------
