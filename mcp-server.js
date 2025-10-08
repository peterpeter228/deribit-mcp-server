import express from 'express';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import fetch from 'node-fetch';

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());

// Deribit API Configuration
const DERIBIT_API_BASE = 'https://www.deribit.com/api/v2';

// Create MCP Server instance
const mcpServer = new Server(
  {
    name: 'deribit-mcp-server',
    version: '1.0.0',
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Define all Deribit tools
const tools = [
  {
    name: 'get_ticker',
    description: 'Get ticker data for a specific instrument including price, volume, and funding rate',
    inputSchema: {
      type: 'object',
      properties: {
        instrument_name: {
          type: 'string',
          description: 'Instrument name (e.g., BTC-PERPETUAL, ETH-PERPETUAL)',
        },
      },
      required: ['instrument_name'],
    },
  },
  {
    name: 'get_instruments',
    description: 'Get all available trading instruments',
    inputSchema: {
      type: 'object',
      properties: {
        currency: {
          type: 'string',
          description: 'Currency symbol (BTC, ETH, USDC, USDT, EURR)',
        },
        kind: {
          type: 'string',
          description: 'Instrument kind (future, option, spot)',
        },
      },
    },
  },
  {
    name: 'get_orderbook',
    description: 'Get order book data for an instrument',
    inputSchema: {
      type: 'object',
      properties: {
        instrument_name: {
          type: 'string',
          description: 'Instrument name',
        },
        depth: {
          type: 'number',
          description: 'Order book depth',
        },
      },
      required: ['instrument_name'],
    },
  },
  {
    name: 'get_funding_rate_history',
    description: 'Get historical funding rate data for perpetual contracts',
    inputSchema: {
      type: 'object',
      properties: {
        instrument_name: {
          type: 'string',
          description: 'Instrument name (must be perpetual)',
        },
        start_timestamp: {
          type: 'number',
          description: 'Start timestamp in milliseconds',
        },
        end_timestamp: {
          type: 'number',
          description: 'End timestamp in milliseconds',
        },
      },
      required: ['instrument_name', 'start_timestamp', 'end_timestamp'],
    },
  },
  {
    name: 'get_index_price',
    description: 'Get index price for a currency',
    inputSchema: {
      type: 'object',
      properties: {
        index_name: {
          type: 'string',
          description: 'Index name (e.g., btc_usd, eth_usd)',
        },
      },
      required: ['index_name'],
    },
  },
];

// Setup tool handlers
mcpServer.setRequestHandler(ListToolsRequestSchema, async () => {
  return { tools };
});

mcpServer.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    let endpoint = '';
    let params = args || {};

    // Map tool names to Deribit endpoints
    switch (name) {
      case 'get_ticker':
        endpoint = '/public/ticker';
        break;
      case 'get_instruments':
        endpoint = '/public/get_instruments';
        break;
      case 'get_orderbook':
        endpoint = '/public/get_order_book';
        break;
      case 'get_funding_rate_history':
        endpoint = '/public/get_funding_rate_history';
        break;
      case 'get_index_price':
        endpoint = '/public/get_index_price';
        break;
      default:
        throw new Error(`Unknown tool: ${name}`);
    }

    // Build URL with query parameters
    const url = new URL(`${DERIBIT_API_BASE}${endpoint}`);
    Object.keys(params).forEach(key => {
      if (params[key] !== undefined && params[key] !== null) {
        url.searchParams.append(key, String(params[key]));
      }
    });

    // Make request to Deribit
    const response = await fetch(url.toString());
    const data = await response.json();

    if (data.error) {
      throw new Error(data.error.message);
    }

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(data.result, null, 2),
        },
      ],
    };
  } catch (error) {
    return {
      content: [
        {
          type: 'text',
          text: `Error: ${error.message}`,
        },
      ],
      isError: true,
    };
  }
});

// SSE endpoint for MCP
app.get('/sse', async (req, res) => {
  console.log('New SSE connection established');
  
  const transport = new SSEServerTransport('/message', res);
  await mcpServer.connect(transport);
  
  // Keep connection alive
  req.on('close', () => {
    console.log('SSE connection closed');
  });
});

// POST endpoint for MCP messages
app.post('/message', async (req, res) => {
  // This will be handled by the SSE transport
  res.status(200).end();
});

// Health check
app.get('/', (req, res) => {
  res.json({
    status: 'ok',
    name: 'Deribit MCP Server',
    version: '1.0.0',
    mcp_endpoint: '/sse',
  });
});

app.listen(PORT, () => {
  console.log(`Deribit MCP Server (SSE) running on port ${PORT}`);
  console.log(`MCP SSE endpoint: http://localhost:${PORT}/sse`);
});