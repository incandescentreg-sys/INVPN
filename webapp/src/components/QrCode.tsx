import QRCode from 'qrcode'
import { useEffect, useState } from 'react'

/** Renders a QR code for the vless:// config so users can scan it. */
export function QrCode({ value, size = 512 }: { value: string; size?: number }) {
  const [dataUrl, setDataUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    QRCode.toDataURL(value, {
      width: size,
      margin: 1,
      errorCorrectionLevel: 'M',
      color: { dark: '#0b1220', light: '#ffffff' },
    })
      .then((url) => {
        if (!cancelled) setDataUrl(url)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [value, size])

  if (failed) {
    return (
      <div className="qr-wrap small muted">
        Не удалось построить QR-код — скопируйте ссылку вручную.
      </div>
    )
  }

  if (!dataUrl) {
    return <div className="skeleton" style={{ width: 240, height: 240, borderRadius: 12 }} />
  }

  return <img className="qr" src={dataUrl} alt="QR-код конфигурации VPN" width={size} height={size} />
}
