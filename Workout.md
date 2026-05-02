Especificación:

El proyecto semestral del curso consiste en analizar vulnerabilidades en software utilizando repositorios provenientes del dataset AIDev.

Cada grupo deberá seleccionar una organización presente en el dataset y trabajar con todos sus repositorios, con un máximo de 50 repositorios por organización.

El objetivo es construir una herramienta compuesta por tres artefactos que permitan detectar, analizar y visualizar vulnerabilidades en los repositorios seleccionados. Para ello, el sistema se organiza en tres componentes: un Miner que extrae vulnerabilidades, un Analyzer que permite estudiarlas mediante notebooks y un Visualizer que presenta resultados consolidados. Note que el análisis que permita realizar su herramienta debe tener un propósito claro. Para ello discutiremos en clases este aspecto.

Debes utilizar Python y JavaScript como lenguajes de implementación. Si algún aspecto no está explícitamente definido, puedes proponer tu propia solución.

Miner
El miner trabaja sobre repositorios de una organización del dataset AIDev y debe ser capaz de procesar múltiples repositorios de forma continua.

Para cada repositorio, el proceso consiste en:

clonar el repositorio
ejecutar análisis de código con CodeQL
generar un SBOM con Syft
detectar vulnerabilidades en dependencias con Grype
Como resultado, el miner debe producir un dataset estructurado que incluya, al menos, el tipo de vulnerabilidad, su ubicación, su severidad (cuando esté disponible) y el repositorio de origen. El formato de salida es libre, pero debe ser consistente y reutilizable.

Analyzer
El analyzer toma como entrada los datos generados por el miner y se implementa mediante notebooks. Su propósito es permitir un análisis exploratorio y sistemático de las vulnerabilidades detectadas.

Se espera que el análisis caracterice las vulnerabilidades en términos de tipo, frecuencia y severidad, además de su distribución entre repositorios. También debe identificar patrones relevantes en los resultados. El grupo puede proponer métricas o enfoques adicionales si lo considera pertinente.


Visualizer
El visualizer presenta los resultados consolidados del análisis de forma clara y comprensible. Debe permitir observar la distribución de vulnerabilidades, comparar repositorios y comunicar diferencias en severidad y tipos.

La representación es libre, pero debe ser coherente con el análisis realizado. Idealmente, el sistema puede actualizar las visualizaciones a medida que se generan nuevos datos.



Arquitectura
Los tres componentes deben implementarse como unidades separadas, cada una con responsabilidades bien definidas. El sistema debe permitir el intercambio de datos entre componentes de forma clara, por ejemplo mediante archivos, APIs o mecanismos de comunicación desacoplados.

La solución debe reflejar explícitamente la separación entre extracción, análisis y visualización.



Reproducibilidad
El sistema debe ser completamente reproducible. Para ello, debes proporcionar una configuración basada en Dev Containers que permita ejecutar el entorno completo sin configuraciones adicionales.

El entorno debe incluir todas las dependencias necesarias, incluyendo CodeQL, Syft, Grype, Python y JavaScript.