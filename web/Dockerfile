# EukaHub web dev image (Phase 0 scaffold).
# A production build (static assets behind a server) is a Phase 5 concern.
FROM node:22-alpine

WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]
