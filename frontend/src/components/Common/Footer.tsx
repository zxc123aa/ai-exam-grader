export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t px-6 py-4">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-2 sm:flex-row">
        <p className="text-xs text-muted-foreground">点凡阅卷 · {currentYear}</p>
        <p className="text-xs text-muted-foreground/70">
          扫描 · 标注 · 批改 · 复核
        </p>
      </div>
    </footer>
  )
}
