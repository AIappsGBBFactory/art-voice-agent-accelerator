# Dockerfile for the frontend React application

# Stage 1: Build the application
FROM node:22-alpine AS builder
WORKDIR /app

# Copy package.json and package-lock.json (or yarn.lock)
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci

# Copy the rest of the application code
COPY . .

# Build the application for production
RUN npm run build

# Stage 2: Serve the application from a lightweight image
FROM node:22-alpine
WORKDIR /app

# Copy only necessary files from the builder stage
COPY --from=builder /app/dist ./dist
COPY package.json package-lock.json ./

# Install only production dependencies (like 'serve')
# 'npm ci --omit=dev' would be better if your 'serve' is in dependencies not devDependencies
# Or, if 'serve' is a regular dependency, 'npm ci' is fine.
# For simplicity, if 'serve' is in dependencies:
RUN npm ci --omit=dev 
# If you added 'serve' as a devDependency, move it to 'dependencies' in package.json
# or install it specifically: RUN npm install serve

# Expose the port the app will run on (this should match your ingressTargetPort in Bicep)
EXPOSE 5173

# Set the PORT environment variable (Azure Container Apps also sets this based on ingress)
ENV PORT=5173

# Command to start the production server
# This will use the 'start' script from package.json if defined as above,
# or you can specify the command directly.
CMD ["npm", "start"]
# Alternatively, directly:
# CMD ["npx", "serve", "-s", "dist", "-l", "tcp://0.0.0.0:5173"]