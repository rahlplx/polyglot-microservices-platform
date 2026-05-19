#!/usr/bin/env python3
"""Merge cover PDF and body PDF into a single final document."""
from pypdf import PdfReader, PdfWriter, Transformation

A4_W, A4_H = 595.28, 841.89

def normalize_page_to_a4(page):
    box = page.mediabox
    w, h = float(box.width), float(box.height)
    if abs(w - A4_W) > 2 or abs(h - A4_H) > 2:
        sx, sy = A4_W / w, A4_H / h
        page.add_transformation(Transformation().scale(sx=sx, sy=sy))
        page.mediabox.lower_left = (0, 0)
        page.mediabox.upper_right = (A4_W, A4_H)
    return page

cover_pdf = '/home/z/my-project/download/cover.pdf'
body_pdf = '/home/z/my-project/download/arch_body.pdf'
output_pdf = '/home/z/my-project/download/Comprehensive_Solution_Architecture.pdf'

writer = PdfWriter()
# Cover as page 1
cover_page = PdfReader(cover_pdf).pages[0]
writer.add_page(normalize_page_to_a4(cover_page))
# Body pages follow
for page in PdfReader(body_pdf).pages:
    writer.add_page(normalize_page_to_a4(page))

writer.add_metadata({
    '/Title': 'Comprehensive Solution Architecture: The Best of Both Worlds',
    '/Author': 'Senior Solution Architect',
    '/Creator': 'Z.ai',
    '/Subject': 'Enterprise Architecture - Agnostic Standards, Decoupled Deployment, Shift-Left Verification'
})
with open(output_pdf, 'wb') as f:
    writer.write(f)

import os
size = os.path.getsize(output_pdf)
print(f"Final PDF: {output_pdf}")
print(f"Size: {size / 1024:.1f} KB")
print(f"Pages: {len(PdfReader(output_pdf).pages)}")
