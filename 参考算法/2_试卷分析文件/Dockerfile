FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY server.js index.html app.js styles.css components.css ./

ENV NODE_ENV=production
EXPOSE 3417

CMD ["node", "server.js"]
