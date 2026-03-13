#!/usr/bin/env python3
"""Capture the website map animation as individual frames using Playwright."""

import os
import time
from playwright.sync_api import sync_playwright

OUTPUT_DIR = "video_assets/map_frames"
FPS = 30
DURATION = 12  # seconds to capture the animation
URL = "http://localhost:8090/"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def capture_map_animation():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # First, get the map section into view and prepare for capture
        # We'll isolate the map-canvas element and make it full-screen
        page.evaluate("""
            () => {
                // Hide everything except the map
                document.body.style.overflow = 'hidden';
                const mapSection = document.getElementById('map-canvas');
                if (!mapSection) return 'no map';

                // Make map section fill the viewport
                const svgEl = mapSection.querySelector('svg');
                if (svgEl) {
                    // Create a full-screen container
                    const container = document.createElement('div');
                    container.id = 'map-capture-container';
                    container.style.cssText = `
                        position: fixed; top: 0; left: 0; width: 1920px; height: 1080px;
                        z-index: 99999; background: #0E1A0E; display: flex;
                        align-items: center; justify-content: center; overflow: hidden;
                    `;

                    // Clone SVG and make it big
                    const svgClone = svgEl.cloneNode(true);
                    svgClone.style.width = '1920px';
                    svgClone.style.height = '1080px';
                    svgClone.setAttribute('viewBox', '0 0 1000 562');
                    svgClone.setAttribute('preserveAspectRatio', 'xMidYMid meet');
                    container.appendChild(svgClone);
                    document.body.appendChild(container);

                    // Remove all 'active' classes and animation states from clone
                    svgClone.querySelectorAll('.active').forEach(el => el.classList.remove('active'));
                    svgClone.querySelectorAll('[style*="opacity"]').forEach(el => {
                        if (el.style.opacity === '0') el.style.opacity = '0';
                    });

                    return 'prepared';
                }
                return 'no svg';
            }
        """)
        page.wait_for_timeout(500)

        # Now trigger the animation step by step using the website's animation logic
        # The website uses data-delay attributes and adds 'active' class
        page.evaluate("""
            () => {
                const container = document.getElementById('map-capture-container');
                if (!container) return;
                const svg = container.querySelector('svg');
                if (!svg) return;

                // Reset: hide everything that should animate
                // Sea shimmer
                svg.querySelectorAll('.map-sea-shimmer').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Land
                svg.querySelectorAll('.map-land').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Coastline
                svg.querySelectorAll('.map-coastline').forEach(el => { el.classList.remove('draw'); el.style.strokeDashoffset = el.getTotalLength ? el.getTotalLength() : 5000; el.style.strokeDasharray = el.getTotalLength ? el.getTotalLength() : 5000; });
                // Terrain
                svg.querySelectorAll('.map-terrain').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Highway
                svg.querySelectorAll('.map-highway').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Labels
                svg.querySelectorAll('.map-hw-label, .map-place-label, .map-sea-label').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Dots
                svg.querySelectorAll('.map-dot').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Pin
                svg.querySelectorAll('.map-pin-group').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                svg.querySelectorAll('.map-pin-ring').forEach(el => { el.classList.remove('active'); });
                svg.querySelectorAll('.map-pin-label').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Routes
                svg.querySelectorAll('.map-route').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Route info
                svg.querySelectorAll('.map-route-info').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Junctions
                svg.querySelectorAll('.map-junction').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Icons
                svg.querySelectorAll('.map-icon').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Scale
                svg.querySelectorAll('.map-scale').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Distance badges
                svg.querySelectorAll('.map-dist-badge').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Hotels
                svg.querySelectorAll('.map-hotel').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });
                // Tower
                svg.querySelectorAll('.map-tower').forEach(el => { el.style.opacity = '0'; el.classList.remove('active'); });

                // Store reference for animation triggering
                window._mapSvg = svg;
                return 'reset complete';
            }
        """)
        page.wait_for_timeout(300)

        # Take initial frame (empty/dark)
        print("Capturing initial frame...")
        page.screenshot(path=os.path.join(OUTPUT_DIR, "frame_0000.png"))

        # Now trigger the animation using the same logic as the website
        # but controlled step by step
        page.evaluate("""
            () => {
                const svg = window._mapSvg;
                if (!svg) return;

                // Replicate startMapAnimation from the website
                // Step 1: Sea shimmer
                svg.querySelectorAll('.map-sea-shimmer').forEach(el => el.classList.add('active'));

                // Step 2: Coastline draw
                const coast = svg.querySelector('.map-coastline');
                if (coast) {
                    coast.classList.add('draw');
                }

                // Step 3: Land reveal (delayed 1s)
                setTimeout(() => {
                    svg.querySelectorAll('.map-land').forEach(el => el.classList.add('active'));
                }, 1000);

                // Step 4: All elements with data-delay
                svg.querySelectorAll('[data-delay]').forEach(el => {
                    const delay = parseInt(el.getAttribute('data-delay'));
                    setTimeout(() => {
                        el.classList.add('active');
                        el.style.opacity = '';  // Remove inline opacity to let CSS take over
                    }, delay);
                });

                // Step 5: Pin group
                const pinGroup = svg.querySelector('.map-pin-group');
                if (pinGroup) {
                    const pinDelay = parseInt(pinGroup.getAttribute('data-delay') || '5400');
                    setTimeout(() => {
                        pinGroup.classList.add('active');
                        pinGroup.style.opacity = '';
                        const ring = svg.querySelector('.map-pin-ring');
                        if (ring) ring.classList.add('active');
                        const pinLabel = svg.querySelector('.map-pin-label');
                        if (pinLabel) { pinLabel.classList.add('active'); pinLabel.style.opacity = ''; }
                    }, pinDelay);
                }

                return 'animation triggered';
            }
        """)

        # Capture frames
        total_frames = DURATION * FPS
        print(f"Capturing {total_frames} frames at {FPS}fps...")

        for i in range(total_frames):
            frame_path = os.path.join(OUTPUT_DIR, f"frame_{i:04d}.png")
            page.screenshot(path=frame_path)
            # Small delay to let animations progress (each frame ~33ms)
            page.wait_for_timeout(33)

            if (i + 1) % 30 == 0:
                print(f"  Frame {i+1}/{total_frames} ({(i+1)/total_frames*100:.0f}%)")

        print(f"Captured {total_frames} frames to {OUTPUT_DIR}/")
        browser.close()

if __name__ == "__main__":
    capture_map_animation()
