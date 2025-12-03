package com.online.shop.ShopOnline.service;

import com.online.shop.ShopOnline.service.OrderService;
import java.util.*;
import java.util.ArrayList;
import java.util.Optional;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders;
import org.springframework.test.web.servlet.result.MockMvcResultMatchers;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.result.MockMvcResultHandlers.print;

@WebMvcTest(OrderService.class)
@ContextConfiguration(classes = {OrderService.class, OrderRepository.class})
public class OrderServiceTest {

    @Autowired
    private MockMvc mvc;

    @MockBean
    private OrderRepository orderRepository;

    @Test
    public void testGetAllOrders() throws Exception {
        when(orderRepository.findAll()).thenReturn(List.of(new Order("123", "John Doe")));

        mvc.perform(MockMvcRequestBuilders.get("/orders")
                .accept(MediaType.APPLICATION_JSON))
                .andDo(print())
                .andExpect(MockMvcResultMatchers.status().isOk());
    }

    @Test
    public void testGetOrderById() throws Exception {
        when(orderRepository.findById("123")).thenReturn(Optional.of(new Order("123", "John Doe")));

        mvc.perform(MockMvcRequestBuilders.get("/orders/123")
                .accept(MediaType.APPLICATION_JSON))
                .andDo(print())
                .andExpect(MockMvcResultMatchers.status().isOk());
    }

    @Test
    public void testCreateOrder() throws Exception {
        Order order = new Order("123", "John Doe");
        when(orderRepository.save(order)).thenReturn(order);

        mvc.perform(MockMvcRequestBuilders.post("/orders")
                .contentType(MediaType.APPLICATION_JSON)
                .content(ObjectMapper.writeValueAsString(order))
                .accept(MediaType.APPLICATION_JSON))
                .andDo(print())
                .andExpect(MockMvcResultMatchers.status().isCreated());
    }

    @Test
    public void testUpdateOrder() throws Exception {
        Order order = new Order("123", "John Doe");
        when(orderRepository.findById("123")).thenReturn(Optional.of(order));
        when(orderRepository.save(order)).thenReturn(order);

        mvc.perform(MockMvcRequestBuilders.put("/orders/123")
                .contentType(MediaType.APPLICATION_JSON)
                .content(ObjectMapper.writeValueAsString(order))
                .accept(MediaType.APPLICATION_JSON))
                .andDo(print())
                .andExpect(MockMvcResultMatchers.status().isOk());
    }

    @Test
    public void testDeleteOrder() throws Exception {
        when(orderRepository.findById("123")).thenReturn(Optional.of(new Order("123", "John Doe")));

        mvc.perform(MockMvcRequestBuilders.delete("/orders/123")
                .accept(MediaType.APPLICATION_JSON))
                .andDo(print())
                .andExpect(MockMvcResultMatchers.status().isOk());
    }
}