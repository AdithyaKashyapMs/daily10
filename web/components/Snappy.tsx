// "Snappy": the mascot shared with EventSnap (the AI Event Photo Discovery Platform).
// A white round-faced character with stick limbs and a yellow flash tuft, drawn as
// inline SVG so it scales cleanly and needs no image files. Daily 10 adds study poses:
// book, papers, pencil and fire (the streak).

export type SnappyPose =
  | 'wave'
  | 'camera'
  | 'selfie'
  | 'search'
  | 'celebrate'
  | 'confused'
  | 'photo'
  | 'shield'
  | 'sad'
  | 'book'
  | 'papers'
  | 'pencil'
  | 'fire'

interface SnappyProps {
  pose?: SnappyPose
  /** Rendered width in pixels (height follows the drawing's proportions). */
  size?: number
  className?: string
  /** Gentle floating animation. */
  bob?: boolean
  /** Accessible description; omit for decorative use. */
  label?: string
}

const INK = 'var(--ink)'
const LIMB = { stroke: INK, strokeWidth: 4.5, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, fill: 'none' }
const OUTLINE = { stroke: INK, strokeWidth: 3 }

function Hand({ x, y }: { x: number; y: number }) {
  return <circle cx={x} cy={y} r={4.2} fill="white" stroke={INK} strokeWidth={2.5} />
}

function Mouth({ pose }: { pose: SnappyPose }) {
  if (pose === 'celebrate' || pose === 'selfie' || pose === 'fire') {
    return <path d="M60 60 Q70 74 80 60 Z" fill={INK} stroke={INK} strokeWidth={2.5} strokeLinejoin="round" />
  }
  if (pose === 'sad') return <path d="M61 66 Q70 58 79 66" {...LIMB} strokeWidth={3} />
  if (pose === 'confused') return <path d="M61 63 Q65.5 59 70 63 T79 63" {...LIMB} strokeWidth={3} />
  return <path d="M61 61 Q70 69 79 61" {...LIMB} strokeWidth={3} />
}

function Arms({ pose }: { pose: SnappyPose }) {
  switch (pose) {
    case 'wave':
      return (
        <>
          <path d="M52 98 L38 118" {...LIMB} />
          <Hand x={38} y={118} />
          <g className="snappy-wave-arm">
            <path d="M88 98 L108 72" {...LIMB} />
            <Hand x={108} y={72} />
          </g>
        </>
      )
    case 'camera':
      return (
        <>
          <path d="M52 96 L47 106" {...LIMB} />
          <path d="M88 96 L93 106" {...LIMB} />
          <rect x={52} y={86} width={11} height={7} rx={2} fill="var(--sun)" stroke={INK} strokeWidth={2.5} />
          <rect x={46} y={91} width={48} height={30} rx={7} fill="var(--sky)" stroke={INK} strokeWidth={3} />
          <circle cx={70} cy={106} r={9.5} fill="white" stroke={INK} strokeWidth={3} />
          <circle cx={70} cy={106} r={4} fill={INK} />
          <Hand x={46} y={108} />
          <Hand x={94} y={108} />
        </>
      )
    case 'selfie':
      return (
        <>
          <path d="M52 98 L40 116" {...LIMB} />
          <Hand x={40} y={116} />
          <path d="M88 98 L106 70" {...LIMB} />
          <rect x={100} y={40} width={20} height={32} rx={5} fill={INK} />
          <rect x={103.5} y={44} width={13} height={21} rx={2.5} fill="var(--sky)" />
          <Hand x={106} y={72} />
        </>
      )
    case 'search':
      return (
        <>
          <path d="M52 98 L42 108 L52 117" {...LIMB} />
          <path d="M88 98 L102 92" {...LIMB} />
          <path d="M104 90 L111 83" stroke={INK} strokeWidth={6} strokeLinecap="round" />
          <circle cx={118} cy={74} r={12} fill="var(--sky-soft)" stroke={INK} strokeWidth={3.5} />
          <path d="M112 70 Q115 66 120 66" stroke="white" strokeWidth={3} strokeLinecap="round" fill="none" />
          <Hand x={102} y={92} />
        </>
      )
    case 'celebrate':
      return (
        <>
          <path d="M52 96 L36 70" {...LIMB} />
          <path d="M88 96 L104 70" {...LIMB} />
          <Hand x={36} y={70} />
          <Hand x={104} y={70} />
          <rect x={18} y={36} width={8} height={8} rx={1.5} fill="var(--sun)" stroke={INK} strokeWidth={2} transform="rotate(20 22 40)" />
          <circle cx={120} cy={34} r={4.5} fill="var(--tomato)" stroke={INK} strokeWidth={2} />
          <rect x={14} y={82} width={9} height={5} rx={1.5} fill="var(--sky)" stroke={INK} strokeWidth={2} transform="rotate(-25 18 84)" />
          <rect x={118} y={90} width={9} height={5} rx={1.5} fill="var(--mint)" stroke={INK} strokeWidth={2} transform="rotate(30 122 92)" />
          <circle cx={30} cy={16} r={3.5} fill="var(--plum)" stroke={INK} strokeWidth={2} />
          <path d="M112 12 L116 20 L108 18 Z" fill="var(--sun)" stroke={INK} strokeWidth={2} strokeLinejoin="round" />
        </>
      )
    case 'confused':
      return (
        <>
          <path d="M52 98 L40 117" {...LIMB} />
          <Hand x={40} y={117} />
          <path d="M88 98 L104 78 L99 60" {...LIMB} />
          <Hand x={99} y={60} />
          <text x={108} y={36} fontSize={30} fontWeight={800} fill="var(--tomato)" stroke={INK} strokeWidth={1.5} fontFamily="var(--font-display)">?</text>
        </>
      )
    case 'photo':
      return (
        <>
          <path d="M52 96 L44 102" {...LIMB} />
          <path d="M88 96 L96 102" {...LIMB} />
          <g transform="rotate(-6 70 104)">
            <rect x={42} y={84} width={56} height={42} rx={4} fill="white" stroke={INK} strokeWidth={3} />
            <rect x={47} y={89} width={46} height={28} rx={2} fill="var(--sky-soft)" stroke={INK} strokeWidth={2} />
            <circle cx={82} cy={96} r={4} fill="var(--sun)" stroke={INK} strokeWidth={1.8} />
            <path d="M47 117 L60 101 L69 110 L76 104 L93 117 Z" fill="var(--mint)" stroke={INK} strokeWidth={2} strokeLinejoin="round" />
          </g>
          <Hand x={44} y={103} />
          <Hand x={96} y={103} />
        </>
      )
    case 'shield':
      return (
        <>
          <path d="M52 98 L44 102" {...LIMB} />
          <path d="M38 84 L56 91 V104 Q56 118 38 126 Q20 118 20 104 V91 Z" fill="var(--mint)" stroke={INK} strokeWidth={3} strokeLinejoin="round" />
          <path d="M30 104 L36 111 L47 97" stroke="white" strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" fill="none" />
          <path d="M88 98 L102 84" {...LIMB} />
          <rect x={98} y={70} width={8} height={13} rx={3} fill="white" stroke={INK} strokeWidth={2.5} />
          <Hand x={102} y={85} />
        </>
      )
    case 'book':
      return (
        <>
          <path d="M52 96 L46 106" {...LIMB} />
          <path d="M88 96 L94 106" {...LIMB} />
          <path d="M70 94 L44 88 V120 L70 126 Z" fill="var(--sky-soft)" stroke={INK} strokeWidth={3} strokeLinejoin="round" />
          <path d="M70 94 L96 88 V120 L70 126 Z" fill="white" stroke={INK} strokeWidth={3} strokeLinejoin="round" />
          <path d="M50 97 L64 100 M50 104 L64 107 M76 100 L90 97 M76 107 L90 104" stroke={INK} strokeWidth={2} strokeLinecap="round" />
          <Hand x={45} y={107} />
          <Hand x={95} y={107} />
        </>
      )
    case 'papers':
      return (
        <>
          <path d="M52 96 L46 108" {...LIMB} />
          <path d="M88 96 L94 108" {...LIMB} />
          <rect x={48} y={78} width={44} height={50} rx={4} fill="var(--sun-soft)" stroke={INK} strokeWidth={3} transform="rotate(-8 70 103)" />
          <rect x={48} y={80} width={44} height={50} rx={4} fill="white" stroke={INK} strokeWidth={3} transform="rotate(5 70 105)" />
          <path d="M56 92 H82 M56 100 H84 M56 108 H78" stroke={INK} strokeWidth={2.2} strokeLinecap="round" transform="rotate(5 70 105)" />
          <path d="M114 74 L114 58 M108 64 L114 58 L120 64" stroke="var(--tomato)" strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" fill="none" />
          <Hand x={46} y={109} />
          <Hand x={94} y={109} />
        </>
      )
    case 'pencil':
      return (
        <>
          <path d="M52 98 L40 117" {...LIMB} />
          <Hand x={40} y={117} />
          <path d="M88 98 L104 84" {...LIMB} />
          <g transform="rotate(35 108 74)">
            <rect x={103} y={50} width={10} height={36} rx={2} fill="var(--sun)" stroke={INK} strokeWidth={2.5} />
            <path d="M103 86 L108 96 L113 86 Z" fill="var(--sun-soft)" stroke={INK} strokeWidth={2.5} strokeLinejoin="round" />
            <rect x={103} y={46} width={10} height={6} rx={2} fill="var(--tomato)" stroke={INK} strokeWidth={2.5} />
          </g>
          <Hand x={104} y={84} />
        </>
      )
    case 'fire':
      return (
        <>
          <path d="M52 96 L36 70" {...LIMB} />
          <path d="M88 96 L104 70" {...LIMB} />
          <Hand x={36} y={70} />
          <Hand x={104} y={70} />
          <path d="M70 128 C52 124 50 106 60 96 C60 104 64 108 68 108 C64 98 70 88 78 84 C76 94 90 100 88 112 C86 122 80 127 70 128 Z"
                fill="var(--tomato)" stroke={INK} strokeWidth={3} strokeLinejoin="round" />
          <path d="M70 126 C62 124 62 114 68 110 C68 116 72 116 74 112 C78 118 78 124 70 126 Z" fill="var(--sun)" stroke={INK} strokeWidth={2} strokeLinejoin="round" />
        </>
      )
    case 'sad':
    default:
      return (
        <>
          <path d="M52 98 L42 120" {...LIMB} />
          <path d="M88 98 L98 120" {...LIMB} />
          <Hand x={42} y={120} />
          <Hand x={98} y={120} />
        </>
      )
  }
}

export default function Snappy({ pose = 'wave', size = 140, className = '', bob = true, label }: SnappyProps) {
  return (
    <svg
      viewBox="0 0 140 160"
      width={size}
      height={(size * 160) / 140}
      className={`${bob ? 'snappy-bob' : ''} ${className}`}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {/* legs */}
      <path d="M62 128 L59 150" {...LIMB} />
      <path d="M78 128 L81 150" {...LIMB} />
      <path d="M53 151 L60 151" {...LIMB} />
      <path d="M80 151 L87 151" {...LIMB} />
      {/* body */}
      <ellipse cx={70} cy={106} rx={22} ry={26} fill="white" {...OUTLINE} />
      {/* flash tuft (drawn before the head so it sprouts from behind it) */}
      <path
        className="snappy-tuft"
        d="M75 1 L64 16 H71.5 L66 28 L82 11 H74.5 L80 1 Z"
        fill="var(--sun)"
        stroke={INK}
        strokeWidth={2.5}
        strokeLinejoin="round"
      />
      {/* head */}
      <circle cx={70} cy={48} r={30} fill="white" {...OUTLINE} />
      <circle cx={52.5} cy={57} r={4.5} fill="var(--tomato)" opacity={0.25} />
      <circle cx={87.5} cy={57} r={4.5} fill="var(--tomato)" opacity={0.25} />
      <ellipse className="snappy-eye" cx={60.5} cy={47} rx={3.6} ry={5.2} fill={INK} />
      <ellipse className="snappy-eye" cx={79.5} cy={47} rx={3.6} ry={5.2} fill={INK} />
      <Mouth pose={pose} />
      {/* arms and props drawn last so they sit in front of the body */}
      <Arms pose={pose} />
    </svg>
  )
}

/** Just the head, for the logo and small badges. */
export function SnappyHead({ size = 36, className = '' }: { size?: number; className?: string }) {
  return (
    <svg viewBox="36 -1 68 82" width={size} height={(size * 82) / 68} className={className} aria-hidden>
      <path d="M75 1 L64 16 H71.5 L66 28 L82 11 H74.5 L80 1 Z" fill="var(--sun)" stroke={INK} strokeWidth={2.5} strokeLinejoin="round" />
      <circle cx={70} cy={48} r={30} fill="white" stroke={INK} strokeWidth={3.5} />
      <ellipse cx={60.5} cy={47} rx={3.8} ry={5.4} fill={INK} />
      <ellipse cx={79.5} cy={47} rx={3.8} ry={5.4} fill={INK} />
      <path d="M61 61 Q70 69 79 61" stroke={INK} strokeWidth={3} strokeLinecap="round" fill="none" />
    </svg>
  )
}
