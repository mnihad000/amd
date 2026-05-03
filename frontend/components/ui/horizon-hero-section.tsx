"use client"

import { useRouter } from "next/navigation"
import { useEffect, useRef, useState } from "react"
import { gsap } from "gsap"
import { ScrollTrigger } from "gsap/ScrollTrigger"
import * as THREE from "three"
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js"
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js"
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js"

import { cn } from "@/lib/utils"

gsap.registerPlugin(ScrollTrigger)

const HERO_SECTIONS = [
  {
    title: "SEARCH",
    lines: [
      "Autonomous source agents gather footage before a dataset exists.",
      "Ranking favors coverage across angle, scale, lighting, and environment.",
    ],
  },
  {
    title: "CURATE",
    lines: [
      "Frame critics cut blur, duplicates, and weak visibility before labeling.",
      "The accepted set stays smaller, cleaner, and easier for YOLO to learn from.",
    ],
  },
  {
    title: "ITERATE",
    lines: [
      "Training, evaluation, and retry logic keep the loop metric-driven.",
      "Weak classes trigger the next collection pass with a clear objective.",
    ],
  },
] as const

const CAMERA_STOPS = [
  { x: 0, y: 30, z: 300 },
  { x: 0, y: 42, z: -60 },
  { x: 0, y: 54, z: -700 },
] as const

type ThreeRefs = {
  scene: THREE.Scene | null
  camera: THREE.PerspectiveCamera | null
  renderer: THREE.WebGLRenderer | null
  composer: EffectComposer | null
  stars: Array<THREE.Points<THREE.BufferGeometry, THREE.ShaderMaterial>>
  nebula: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial> | null
  mountains: Array<THREE.Mesh<THREE.ShapeGeometry, THREE.MeshBasicMaterial>>
  atmosphere: THREE.Mesh<THREE.SphereGeometry, THREE.ShaderMaterial> | null
  animationId: number | null
  locations: number[]
  targetCameraX?: number
  targetCameraY?: number
  targetCameraZ?: number
}

export type HorizonHeroSectionProps = {
  className?: string
  ctaHref?: string
}

export function HorizonHeroSection({
  className,
  ctaHref = "/app",
}: HorizonHeroSectionProps) {
  const router = useRouter()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const titleRef = useRef<HTMLHeadingElement | null>(null)
  const subtitleRef = useRef<HTMLDivElement | null>(null)
  const scrollProgressRef = useRef<HTMLDivElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)

  const [scrollProgress, setScrollProgress] = useState(0)
  const [currentSection, setCurrentSection] = useState(0)
  const [isReady, setIsReady] = useState(false)

  const smoothCameraPos = useRef({
    ...CAMERA_STOPS[0],
  })

  const threeRefs = useRef<ThreeRefs>({
    scene: null,
    camera: null,
    renderer: null,
    composer: null,
    stars: [],
    nebula: null,
    mountains: [],
    atmosphere: null,
    animationId: null,
    locations: [],
  })

  const totalSections = HERO_SECTIONS.length
  const scrollRange = Math.max(totalSections - 1, 1)
  const activeSection = HERO_SECTIONS[currentSection] ?? HERO_SECTIONS[0]
  const isLastSection = scrollProgress >= 0.82

  useEffect(() => {
    const canvas = canvasRef.current

    if (!canvas) {
      return
    }

    const refs = threeRefs.current
    const isCompactViewport = window.matchMedia("(max-width: 768px)").matches
    const initialCameraPosition = CAMERA_STOPS[0]
    const starCount = isCompactViewport ? 1800 : 4200

    smoothCameraPos.current = { ...initialCameraPosition }

    refs.scene = new THREE.Scene()
    refs.scene.fog = new THREE.FogExp2(0x050816, 0.00028)

    refs.camera = new THREE.PerspectiveCamera(
      isCompactViewport ? 68 : 75,
      window.innerWidth / window.innerHeight,
      0.1,
      2000
    )
    refs.camera.position.set(
      initialCameraPosition.x,
      initialCameraPosition.y,
      initialCameraPosition.z
    )
    refs.camera.lookAt(0, 10, -600)

    refs.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
    })
    refs.renderer.setSize(window.innerWidth, window.innerHeight)
    refs.renderer.setPixelRatio(
      Math.min(window.devicePixelRatio, isCompactViewport ? 1.5 : 2)
    )
    refs.renderer.toneMapping = THREE.ACESFilmicToneMapping
    refs.renderer.toneMappingExposure = 0.6

    refs.composer = new EffectComposer(refs.renderer)
    refs.composer.addPass(new RenderPass(refs.scene, refs.camera))
    refs.composer.addPass(
      new UnrealBloomPass(
        new THREE.Vector2(window.innerWidth, window.innerHeight),
        isCompactViewport ? 0.45 : 0.7,
        0.4,
        0.9
      )
    )

    const createStarField = () => {
      if (!refs.scene) {
        return
      }

      for (let layerIndex = 0; layerIndex < 3; layerIndex += 1) {
        const geometry = new THREE.BufferGeometry()
        const positions = new Float32Array(starCount * 3)
        const colors = new Float32Array(starCount * 3)
        const sizes = new Float32Array(starCount)

        for (let starIndex = 0; starIndex < starCount; starIndex += 1) {
          const radius = 200 + Math.random() * 850
          const theta = Math.random() * Math.PI * 2
          const phi = Math.acos(Math.random() * 2 - 1)

          positions[starIndex * 3] = radius * Math.sin(phi) * Math.cos(theta)
          positions[starIndex * 3 + 1] =
            radius * Math.sin(phi) * Math.sin(theta)
          positions[starIndex * 3 + 2] = radius * Math.cos(phi)

          const color = new THREE.Color()
          const colorChoice = Math.random()

          if (colorChoice < 0.6) {
            color.setHSL(0.58, 0.22, 0.84 + Math.random() * 0.1)
          } else if (colorChoice < 0.86) {
            color.setHSL(0.54, 0.65, 0.65)
          } else {
            color.setHSL(0.13, 0.8, 0.62)
          }

          colors[starIndex * 3] = color.r
          colors[starIndex * 3 + 1] = color.g
          colors[starIndex * 3 + 2] = color.b
          sizes[starIndex] = Math.random() * 1.8 + 0.4
        }

        geometry.setAttribute(
          "position",
          new THREE.BufferAttribute(positions, 3)
        )
        geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3))
        geometry.setAttribute("size", new THREE.BufferAttribute(sizes, 1))

        const material = new THREE.ShaderMaterial({
          uniforms: {
            time: { value: 0 },
            depth: { value: layerIndex },
          },
          vertexShader: `
            attribute float size;
            attribute vec3 color;
            varying vec3 vColor;
            uniform float time;
            uniform float depth;

            void main() {
              vColor = color;
              vec3 pos = position;

              float angle = time * 0.05 * (1.0 - depth * 0.3);
              mat2 rot = mat2(cos(angle), -sin(angle), sin(angle), cos(angle));
              pos.xy = rot * pos.xy;

              vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
              gl_PointSize = size * (280.0 / -mvPosition.z);
              gl_Position = projectionMatrix * mvPosition;
            }
          `,
          fragmentShader: `
            varying vec3 vColor;

            void main() {
              float dist = length(gl_PointCoord - vec2(0.5));
              if (dist > 0.5) discard;

              float opacity = 1.0 - smoothstep(0.0, 0.5, dist);
              gl_FragColor = vec4(vColor, opacity);
            }
          `,
          transparent: true,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        })

        const stars = new THREE.Points(geometry, material)
        refs.scene.add(stars)
        refs.stars.push(stars)
      }
    }

    const createNebula = () => {
      if (!refs.scene) {
        return
      }

      const geometry = new THREE.PlaneGeometry(8000, 4000, 100, 100)
      const material = new THREE.ShaderMaterial({
        uniforms: {
          time: { value: 0 },
          color1: { value: new THREE.Color(0x2563eb) },
          color2: { value: new THREE.Color(0x14b8a6) },
          opacity: { value: isCompactViewport ? 0.24 : 0.3 },
        },
        vertexShader: `
          varying vec2 vUv;
          varying float vElevation;
          uniform float time;

          void main() {
            vUv = uv;
            vec3 pos = position;

            float elevation = sin(pos.x * 0.01 + time) * cos(pos.y * 0.01 + time) * 20.0;
            pos.z += elevation;
            vElevation = elevation;

            gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
          }
        `,
        fragmentShader: `
          uniform vec3 color1;
          uniform vec3 color2;
          uniform float opacity;
          uniform float time;
          varying vec2 vUv;
          varying float vElevation;

          void main() {
            float mixFactor = sin(vUv.x * 10.0 + time) * cos(vUv.y * 10.0 + time);
            vec3 color = mix(color1, color2, mixFactor * 0.5 + 0.5);

            float alpha = opacity * (1.0 - length(vUv - 0.5) * 2.0);
            alpha *= 1.0 + vElevation * 0.01;

            gl_FragColor = vec4(color, alpha);
          }
        `,
        transparent: true,
        blending: THREE.AdditiveBlending,
        side: THREE.DoubleSide,
        depthWrite: false,
      })

      refs.nebula = new THREE.Mesh(geometry, material)
      refs.nebula.position.z = -1050
      refs.scene.add(refs.nebula)
    }

    const createMountains = () => {
      if (!refs.scene) {
        return
      }

      const layers = [
        { distance: -50, height: 60, color: 0x0f172a, opacity: 1 },
        { distance: -100, height: 85, color: 0x111827, opacity: 0.88 },
        { distance: -150, height: 105, color: 0x1e293b, opacity: 0.68 },
        { distance: -200, height: 125, color: 0x0f3b4f, opacity: 0.44 },
      ]

      layers.forEach((layer, index) => {
        const points: THREE.Vector2[] = []
        const segments = 50

        for (let pointIndex = 0; pointIndex <= segments; pointIndex += 1) {
          const x = (pointIndex / segments - 0.5) * 1000
          const y =
            Math.sin(pointIndex * 0.1) * layer.height +
            Math.sin(pointIndex * 0.05) * layer.height * 0.5 +
            Math.random() * layer.height * 0.2 -
            100

          points.push(new THREE.Vector2(x, y))
        }

        points.push(new THREE.Vector2(5000, -300))
        points.push(new THREE.Vector2(-5000, -300))

        const geometry = new THREE.ShapeGeometry(new THREE.Shape(points))
        const material = new THREE.MeshBasicMaterial({
          color: layer.color,
          transparent: true,
          opacity: layer.opacity,
          side: THREE.DoubleSide,
        })

        const mountain = new THREE.Mesh(geometry, material)
        mountain.position.z = layer.distance
        mountain.position.y = layer.distance
        mountain.userData = { baseZ: layer.distance, index }

        refs.scene?.add(mountain)
        refs.mountains.push(mountain)
      })
    }

    const createAtmosphere = () => {
      if (!refs.scene) {
        return
      }

      const geometry = new THREE.SphereGeometry(600, 32, 32)
      const material = new THREE.ShaderMaterial({
        uniforms: {
          time: { value: 0 },
        },
        vertexShader: `
          varying vec3 vNormal;

          void main() {
            vNormal = normalize(normalMatrix * normal);
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `,
        fragmentShader: `
          varying vec3 vNormal;
          uniform float time;

          void main() {
            float intensity = pow(0.7 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 2.0);
            vec3 atmosphere = vec3(0.18, 0.55, 1.0) * intensity;

            float pulse = sin(time * 2.0) * 0.08 + 0.92;
            atmosphere *= pulse;

            gl_FragColor = vec4(atmosphere, intensity * 0.22);
          }
        `,
        side: THREE.BackSide,
        blending: THREE.AdditiveBlending,
        transparent: true,
      })

      refs.atmosphere = new THREE.Mesh(geometry, material)
      refs.scene.add(refs.atmosphere)
    }

    const rememberMountainLocations = () => {
      refs.locations = refs.mountains.map((mountain) => mountain.position.z)
    }

    const animate = () => {
      refs.animationId = window.requestAnimationFrame(animate)

      const time = Date.now() * 0.001

      refs.stars.forEach((starField) => {
        starField.material.uniforms.time.value = time
      })

      if (refs.nebula) {
        refs.nebula.material.uniforms.time.value = time * 0.5
      }

      if (refs.atmosphere) {
        refs.atmosphere.material.uniforms.time.value = time
      }

      if (
        refs.camera &&
        refs.targetCameraX !== undefined &&
        refs.targetCameraY !== undefined &&
        refs.targetCameraZ !== undefined
      ) {
        const smoothingFactor = isCompactViewport ? 0.07 : 0.05

        smoothCameraPos.current.x +=
          (refs.targetCameraX - smoothCameraPos.current.x) * smoothingFactor
        smoothCameraPos.current.y +=
          (refs.targetCameraY - smoothCameraPos.current.y) * smoothingFactor
        smoothCameraPos.current.z +=
          (refs.targetCameraZ - smoothCameraPos.current.z) * smoothingFactor

        const floatX = Math.sin(time * 0.1) * 2
        const floatY = Math.cos(time * 0.15) * 1

        refs.camera.position.x = smoothCameraPos.current.x + floatX
        refs.camera.position.y = smoothCameraPos.current.y + floatY
        refs.camera.position.z = smoothCameraPos.current.z
        refs.camera.lookAt(0, 10, -600)
      }

      refs.mountains.forEach((mountain, index) => {
        const parallaxFactor = 1 + index * 0.45
        mountain.position.x = Math.sin(time * 0.1) * 2 * parallaxFactor
        mountain.position.y = 50 + Math.cos(time * 0.15) * parallaxFactor
      })

      refs.composer?.render()
    }

    createStarField()
    createNebula()
    createMountains()
    createAtmosphere()
    rememberMountainLocations()

    refs.targetCameraX = initialCameraPosition.x
    refs.targetCameraY = initialCameraPosition.y
    refs.targetCameraZ = initialCameraPosition.z

    animate()
    setIsReady(true)

    const handleResize = () => {
      if (!refs.camera || !refs.renderer || !refs.composer) {
        return
      }

      refs.camera.aspect = window.innerWidth / window.innerHeight
      refs.camera.updateProjectionMatrix()
      refs.renderer.setSize(window.innerWidth, window.innerHeight)
      refs.composer.setSize(window.innerWidth, window.innerHeight)
    }

    window.addEventListener("resize", handleResize)

    return () => {
      if (refs.animationId) {
        window.cancelAnimationFrame(refs.animationId)
      }

      window.removeEventListener("resize", handleResize)

      refs.stars.forEach((starField) => {
        starField.geometry.dispose()
        starField.material.dispose()
      })

      refs.mountains.forEach((mountain) => {
        mountain.geometry.dispose()
        mountain.material.dispose()
      })

      refs.nebula?.geometry.dispose()
      refs.nebula?.material.dispose()
      refs.atmosphere?.geometry.dispose()
      refs.atmosphere?.material.dispose()
      refs.renderer?.dispose()
      refs.scene?.clear()

      refs.stars = []
      refs.mountains = []
      refs.nebula = null
      refs.atmosphere = null
      refs.renderer = null
      refs.composer = null
      refs.scene = null
      refs.camera = null
      refs.animationId = null
    }
  }, [])

  useEffect(() => {
    if (!isReady) {
      return
    }

    gsap.set(
      [menuRef.current, titleRef.current, subtitleRef.current, scrollProgressRef.current],
      {
        visibility: "visible",
      }
    )

    const introTimeline = gsap.timeline()

    if (menuRef.current) {
      introTimeline.from(menuRef.current, {
        x: -64,
        opacity: 0,
        duration: 0.9,
        ease: "power3.out",
      })
    }

    if (scrollProgressRef.current) {
      introTimeline.from(
        scrollProgressRef.current,
        {
          opacity: 0,
          y: 36,
          duration: 0.8,
          ease: "power2.out",
        },
        "-=0.55"
      )
    }

    return () => {
      introTimeline.kill()
    }
  }, [isReady])

  useEffect(() => {
    if (!isReady) {
      return
    }

    const titleChars =
      titleRef.current?.querySelectorAll<HTMLElement>(".title-char") ?? []
    const subtitleLines =
      subtitleRef.current?.querySelectorAll<HTMLElement>(".subtitle-line") ?? []

    const contentTimeline = gsap.timeline()

    contentTimeline.fromTo(
      titleChars,
      {
        y: 72,
        opacity: 0,
      },
      {
        y: 0,
        opacity: 1,
        duration: 0.85,
        stagger: 0.04,
        ease: "power4.out",
      }
    )

    contentTimeline.fromTo(
      subtitleLines,
      {
        y: 32,
        opacity: 0,
      },
      {
        y: 0,
        opacity: 1,
        duration: 0.7,
        stagger: 0.12,
        ease: "power3.out",
      },
      "-=0.45"
    )

    return () => {
      contentTimeline.kill()
    }
  }, [currentSection, isReady])

  useEffect(() => {
    const handleScroll = () => {
      const documentHeight = document.documentElement.scrollHeight
      const maxScroll = Math.max(documentHeight - window.innerHeight, 1)
      const progress = Math.min(window.scrollY / maxScroll, 1)
      const refs = threeRefs.current
      const sectionFloat = progress * scrollRange
      const lowerSectionIndex = Math.min(
        Math.floor(sectionFloat),
        CAMERA_STOPS.length - 2
      )
      const sectionProgress = sectionFloat - lowerSectionIndex
      const currentPos = CAMERA_STOPS[lowerSectionIndex] ?? CAMERA_STOPS[0]
      const nextPos = CAMERA_STOPS[lowerSectionIndex + 1] ?? currentPos
      const nextSection = Math.min(Math.round(sectionFloat), totalSections - 1)

      setScrollProgress(progress)
      setCurrentSection((previous) =>
        previous === nextSection ? previous : nextSection
      )

      refs.targetCameraX =
        currentPos.x + (nextPos.x - currentPos.x) * sectionProgress
      refs.targetCameraY =
        currentPos.y + (nextPos.y - currentPos.y) * sectionProgress
      refs.targetCameraZ =
        currentPos.z + (nextPos.z - currentPos.z) * sectionProgress

      refs.mountains.forEach((mountain, index) => {
        const baseZ = refs.locations[index] ?? (mountain.userData.baseZ as number)
        mountain.position.z = baseZ + sectionFloat * (42 + index * 18)
      })

      if (refs.nebula) {
        refs.nebula.position.z = -1050 + progress * 200
      }
    }

    window.addEventListener("scroll", handleScroll, { passive: true })
    handleScroll()

    return () => {
      window.removeEventListener("scroll", handleScroll)
    }
  }, [scrollRange, totalSections])

  const splitTitle = (text: string) => {
    return Array.from(text).map((char, index) => (
      <span key={`${char}-${index}`} className="title-char">
        {char === " " ? "\u00A0" : char}
      </span>
    ))
  }

  return (
    <div ref={containerRef} className={cn("hero-container cosmos-style", className)}>
      <canvas ref={canvasRef} className="hero-canvas" />

      <div className="hero-overlay">
        <div className="hero-shell">
          <div ref={menuRef} className="side-menu" style={{ visibility: "hidden" }}>
            <div className="menu-icon" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <div className="vertical-text">AMD</div>
          </div>

          <div className="hero-content cosmos-content">
            <p className="hero-eyebrow">Autonomous Dataset Agent</p>
            <h1
              key={activeSection.title}
              ref={titleRef}
              className="hero-title"
            >
              {splitTitle(activeSection.title)}
            </h1>

            <div
              key={`${activeSection.title}-subtitle`}
              ref={subtitleRef}
              className="hero-subtitle cosmos-subtitle"
            >
              {activeSection.lines.map((line) => (
                <p key={line} className="subtitle-line">
                  {line}
                </p>
              ))}
            </div>

            <button
              type="button"
              onClick={() => router.push(ctaHref)}
              className={cn("hero-cta", isLastSection && "hero-cta-visible")}
            >
              Get Started
            </button>
          </div>

          <div
            ref={scrollProgressRef}
            className="scroll-progress"
            style={{ visibility: "hidden" }}
          >
            <div className="scroll-text">Pipeline Progress</div>
            <div className="progress-track" aria-hidden="true">
              <div
                className="progress-fill"
                style={{ width: `${scrollProgress * 100}%` }}
              />
            </div>
            <div className="section-counter">
              {String(currentSection + 1).padStart(2, "0")} /{" "}
              {String(totalSections).padStart(2, "0")}
            </div>
          </div>
        </div>
      </div>

      <div className="scroll-sections" aria-hidden="true">
        {HERO_SECTIONS.map((section) => (
          <section key={section.title} className="content-section">
            <span className="content-marker">{section.title}</span>
          </section>
        ))}
      </div>
    </div>
  )
}

export const Component = HorizonHeroSection

export default HorizonHeroSection
