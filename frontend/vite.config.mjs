export default {
  server: { proxy: { '/api': process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', globals: false },
}
