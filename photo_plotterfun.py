"""Python ports of Plotterfun's springs, halftone and boxes algorithms.

Derived from https://github.com/mitxela/plotterfun, revision
faf67d4dadc359a9d5703b0c4e501ea3bbad84d9.
Copyright (c) 2020 Tim Alex Jacobs (mitxela).
Boxes by MarkJB; halftone by HomineLudens, per the upstream README.
Distributed under the MIT license in third_party/plotterfun-LICENSE.txt.
Adaptations use millimeters, seeded randomness, bounded work and clipped paths.
"""
import math


def plotterfun_paths(style, ink, width, height, spacing, rng, threshold):
    def clip(x, y):
        return min(width, max(0, x)), min(height, max(0, y))

    if style == "springs":
        rows = max(1, math.ceil(height / spacing))
        samples = min(78000 // rows, max(2, math.ceil(width / (spacing / 14))))
        for row in range(rows):
            cy = min(height, (row + .5) * spacing)
            path = []
            for i in range(samples):
                x = width * i / (samples - 1)
                amplitude = spacing * .8 * ink(x, cy)
                phase = x / (spacing * .8) * math.tau
                path.append(clip(x + amplitude * math.cos(phase),
                                 cy + amplitude * math.sin(phase)))
            yield path if row % 2 == 0 else list(reversed(path))
    else:
        spacing = max(spacing * 1.4, math.sqrt(width * height / 7000))
        for row in range(math.ceil(height / spacing)):
            cy = (row + .5) * spacing
            if cy >= height:
                continue
            columns = range(math.ceil(width / spacing))
            if row % 2:
                columns = reversed(columns)
            for column in columns:
                cx = (column + .5) * spacing
                if cx >= width:
                    continue
                tone = ink(cx, cy)
                if tone <= threshold:
                    continue
                radius = spacing * .48 * tone
                if style == "halftone":
                    yield [clip(cx + radius * math.cos(i * math.tau / 16),
                                cy + radius * math.sin(i * math.tau / 16))
                           for i in range(17)]
                elif style == "boxes":
                    yield [clip(cx + dx * radius, cy + dy * radius)
                           for dx, dy in ((-1,-1),(1,-1),(1,1),(-1,1),(-1,-1))]
