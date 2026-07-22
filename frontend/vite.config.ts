import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig, type Plugin } from "vite"

const appVersion =
  process.env.VITE_APP_VERSION?.trim() || new Date().toISOString()

const routeSplitFullReload = (): Plugin => {
  let reloadTimer: ReturnType<typeof setTimeout> | undefined

  return {
    name: "route-split-full-reload",
    apply: "serve",
    enforce: "post",
    handleHotUpdate({ file, server }) {
      const normalizedFile = file.replaceAll("\\", "/")
      const isRouteFile =
        normalizedFile.includes("/src/routes/") &&
        /\.(?:ts|tsx)$/.test(normalizedFile)
      const isGeneratedRouteTree = normalizedFile.endsWith(
        "/src/routeTree.gen.ts",
      )

      if (!isRouteFile && !isGeneratedRouteTree) return

      if (reloadTimer) clearTimeout(reloadTimer)
      reloadTimer = setTimeout(() => {
        server.ws.send({ type: "full-reload", path: "*" })
      }, 50)
    },
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    watch: {
      usePolling: true,
      interval: 300,
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  plugins: [
    tanstackRouter({
      target: "react",
      autoCodeSplitting: true,
    }),
    react(),
    tailwindcss(),
    routeSplitFullReload(),
  ],
})
