package com.online.shop.ShopOnline.controller;

import com.online.shop.ShopOnline.controller.OrderController;
import com.online.shop.ShopOnline.model.Order;
import com.online.shop.ShopOnline.service.OrderService;
import java.util.*;
import java.util.ArrayList;
import java.util.Optional;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.BeforeEach;
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
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(OrderController.class)
@ContextConfiguration(classes = {OrderService.class})
public class OrderControllerTest {

    private MockMvc mvc;

    @Autowired
    private MockMvc mockMvc;

    private Order order;
    private OrderService orderService;

    @BeforeEach
    public void setup() {
        order = new Order();
        order.setId(1);
        order.setName("Order 1");
        order.setDescription("This is an order description");

        orderService = Mockito.mock(OrderService.class);

        when(orderService.getOrder(1)).thenReturn(order);
    }

    @Test
    public void testGetAllOrders() throws Exception {
        mvc.perform(get("/orders"))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON_UTF8));
    }

    @Test
    public void testGetOrderById() throws Exception {
        mvc.perform(get("/orders/{id}", 1))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON_UTF8));
    }

    @Test
    public void testCreateOrder() throws Exception {
        mvc.perform(post("/orders")
                .contentType(MediaType.APPLICATION_JSON_UTF8)
                .content("{\"name\":\"New Order\",\"description\":\"This is a new order\"}")
                .accept(MediaType.APPLICATION_JSON_UTF8))
                .andExpect(status().isCreated());
    }

    @Test
    public void testUpdateOrder() throws Exception {
        mvc.perform(put("/orders/{id}", 1)
                .contentType(MediaType.APPLICATION_JSON_UTF8)
                .content("{\"name\":\"Updated Order\",\"description\":\"This is an updated order\"}")
                .accept(MediaType.APPLICATION_JSON_UTF8))
                .andExpect(status().isOk());
    }

    @Test
    public void testDeleteOrder() throws Exception {
        mvc.perform(delete("/orders/{id}", 1))
                .andExpect(status().isNoContent());
    }
}