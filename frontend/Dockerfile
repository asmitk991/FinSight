# Stage 1: Build
FROM node:20-slim AS build

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# Set build-time env for API and Supabase
ARG VITE_API_URL
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY

ENV VITE_API_URL=$VITE_API_URL
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY

RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:alpine

# Copy build artifacts from stage 1
COPY --from=build /app/dist /usr/share/nginx/html

# Expose port (Nginx default)
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
