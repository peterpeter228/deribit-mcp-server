import express from 'express';
import { spawn } from 'child_process';

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());

// Health check endpoint
app.get('/', (req, res) => {
  res.json({
    status: 'ok',
    service: 'Deribit MCP Server',
    version: '1.0.0',
    endpoints: {
      tools: '/tools',
      call: '/call'
    }
  });
});

// Get available tools
app.get('/tools', (req, res) => {
  const tools = [
    'get_instruments',
    'get_ticker',
    'get_tickers',
    'get_orderbook',
    'get_tradingview_chart',
    'get_last_trades',
    'get_funding_rate_history',
    'get_funding_rate_value',
    'get_index_price',
    'get_volatility_index',
    'get_historical_volatility',
    'get_book_summary_by_currency',
    'get_book_summary_by_instrument',
    'get_delivery_prices',
    'ticker_statistics'
  ];
  
  res.json({ tools });
});

// Call a tool
app.post('/call', async (req, res) => {
  const { tool, params } = req.body;
  
  if (!tool) {
    return res.status(400).json({ error: 'Tool name is required' });
  }

  try {
    // Make direct API call to Deribit
    const DERIBIT_API_BASE = 'https://www.deribit.com/api/v2';
    
    let endpoint = '';
    let queryParams = params || {};
    
    // Map tool names to Deribit API endpoints
    switch (tool) {
      case 'get_instruments':
        endpoint = '/public/get_instruments';
        break;
      case 'get_ticker':
        endpoint = '/public/ticker';
        break;
      case 'get_tickers':
        endpoint = '/public/get_book_summary_by_currency';
        break;
      case 'get_orderbook':
        endpoint = '/public/get_order_book';
        break;
      case 'get_tradingview_chart':
        endpoint = '/public/get_tradingview_chart_data';
        break;
      case 'get_last_trades':
        endpoint = '/public/get_last_trades_by_instrument';
        break;
      case 'get_funding_rate_history':
        endpoint = '/public/get_funding_rate_history';
        break;
      case 'get_funding_rate_value':
        endpoint = '/public/get_funding_rate_value';
        break;
      case 'get_index_price':
        endpoint = '/public/get_index_price';
        break;
      case 'get_volatility_index':
        endpoint = '/public/get_volatility_index_data';
        break;
      case 'get_historical_volatility':
        endpoint = '/public/get_historical_volatility';
        break;
      case 'get_book_summary_by_currency':
        endpoint = '/public/get_book_summary_by_currency';
        break;
      case 'get_book_summary_by_instrument':
        endpoint = '/public/get_book_summary_by_instrument';
        break;
      case 'get_delivery_prices':
        endpoint = '/public/get_delivery_prices';
        break;
      case 'ticker_statistics':
        endpoint = '/public/ticker';
        break;
      default:
        return res.status(400).json({ error: `Unknown tool: ${tool}` });
    }
    
    // Build URL with query parameters
    const url = new URL(`${DERIBIT_API_BASE}${endpoint}`);
    Object.keys(queryParams).forEach(key => {
      if (queryParams[key] !== undefined && queryParams[key] !== null) {
        url.searchParams.append(key, String(queryParams[key]));
      }
    });
    
    // Make request to Deribit
    const response = await fetch(url.toString());
    const data = await response.json();
    
    if (data.error) {
      return res.status(400).json({ error: data.error.message });
    }
    
    res.json({ result: data.result });
    
  } catch (error) {
    console.error('Error calling tool:', error);
    res.status(500).json({ error: error.message });
  }
});

app.listen(PORT, () => {
  console.log(`Deribit MCP HTTP Server running on port ${PORT}`);
});