# RISK — roundtrip a Polarion (inmutabilidad estructural)

El entregable se **importa de vuelta** a Polarion. Si la cirugía de s7 no es
perfecta, Polarion duplica requisitos o falla el import. Reglas, con las
cicatrices de reqif-extractor y de un pipeline anterior detrás de cada una:

## Prohibido (romperlo = import roto o duplicados)

1. **Tocar cualquier `IDENTIFIER`** (SPEC-OBJECT, SPEC-HIERARCHY, SPEC-TYPES,
   ATTRIBUTE-DEFINITION, ENUM-VALUE, SPECIFICATION). Polarion casa el roundtrip
   por esos IDs: si cambian, el import crea duplicados en vez de actualizar.
   *(Cicatriz: IDs compartidos/regenerados → "Unresolved parent key: null".)*
2. **Regenerar el archivo desde plantilla.** El STK trae SPEC-TYPES, atributos
   custom y metadatos del proyecto de origen que no controlamos. Se edita el
   original con lxml; nunca se reconstruye.
3. **Alterar la jerarquía** (`SPEC-HIERARCHY`) o el orden de los SPEC-OBJECTS.
   *(Cicatriz: Polarion renumera outline por posición del árbol, no por etiqueta.)*
4. **Escribir XHTML multi-bloque.** Todo valor XHTML nuevo (rationale, config)
   va con **UN solo `<xhtml:div>` raíz**, compactado.
   *(Cicatriz: multi-bloque suelto rompía el import — bug v7_flatten.)*
5. **Status como texto libre.** Solo `ATTRIBUTE-VALUE-ENUMERATION` con
   `ENUM-VALUE-REF` a un IDENTIFIER que YA exista en el archivo. Si el STK no
   trae un valor de la taxonomía, NO se inventa el enum-value: se reporta.

## Obligatorio en s7

- Preservar declaración XML, encoding, namespaces y (en lo posible) el formato
  de serialización original — lxml tiende a "normalizar"; hay que medirlo con
  `tools/roundtrip_diff.py`.
- Si el campo objetivo ya trae valor (ATTRIBUTE-VALUE existente), se REEMPLAZA
  el valor; si no existe, se AÑADE el ATTRIBUTE-VALUE dentro de `<VALUES>` del
  SPEC-OBJECT — nunca se toca la definición del atributo.
- `LAST-CHANGE`: actualizar solo el de los SPEC-OBJECTS modificados (a decidir
  con un import de prueba: ¿Polarion lo exige o lo ignora?).

## Verificación (tools/roundtrip_diff.py)

Diff estructural original ↔ salida que garantiza:
- Mismo conjunto exacto de IDENTIFIERs (ninguno nuevo salvo quizá
  ATTRIBUTE-VALUEs añadidos, ningún desaparecido).
- SPEC-TYPES y SPEC-HIERARCHY byte-idénticos (normalizando LAST-CHANGE).
- Las únicas diferencias permitidas: contenido de los ATTRIBUTE-VALUE de los
  campos objetivo (status/comments/config) de los SPEC-OBJECTS.
- XML bien formado + cada XHTML nuevo con un único div raíz.

**La prueba de fuego sigue siendo un import real en Polarion** (proyecto de
prueba, documento desechable) antes de dar nada por bueno.
