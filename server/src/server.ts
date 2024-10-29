import express from 'express';
import { config } from 'dotenv';
import cors from 'cors';
import { setupRoutes } from './routes';

config();

const app = express();
const port = process.env.PORT || 3000;

const corsOptions = {
    origin: ["http://localhost:5173", "https://verdad-frontend.fly.dev", "https://verdad.app"],
    optionsSuccessStatus: 200,
};

// Middleware
app.use(cors(corsOptions));
app.use(express.json());

// Setup routes
setupRoutes(app);

// Start server
app.listen(port, () => {
    console.log(`Server is running at :${port}`);
});

export default app;